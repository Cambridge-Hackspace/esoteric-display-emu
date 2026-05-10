use clap::Parser;
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use ratatui::{
    Terminal,
    backend::{Backend, CrosstermBackend},
    layout::Alignment,
    style::{Color, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph},
};
use std::{
    io,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::net::UdpSocket;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(long)]
    width: usize,
    #[arg(long)]
    height: usize,
    #[arg(long)]
    bind: String,
    #[arg(long)]
    colors: bool,
    #[arg(long)]
    clock: f64,
}

struct AppState {
    frame_data: Vec<u8>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();

    let expected_bytes = if args.colors {
        args.width * args.height * 3
    } else {
        args.width * args.height
    };

    let state = Arc::new(Mutex::new(AppState {
        frame_data: vec![0; expected_bytes],
    }));

    let bind_addr = args.bind.clone();
    let state_clone = Arc::clone(&state);

    tokio::spawn(async move {
        let socket = UdpSocket::bind(&bind_addr)
            .await
            .expect("Failed to bind UDP socket");
        let mut buf = [0u8; 2048];

        loop {
            if let Ok((size, _)) = socket.recv_from(&mut buf).await {
                // process 10-byte DDP header
                if size > 10 {
                    // extract length from DDP header (bytes 8 and 9, big endian)
                    let payload_len = u16::from_be_bytes([buf[8], buf[9]]) as usize;
                    let end_idx = 10 + payload_len;

                    if size >= end_idx {
                        let payload = &buf[10..end_idx];
                        let mut lock = state_clone.lock().unwrap();

                        let copy_len = payload.len().min(lock.frame_data.len());
                        lock.frame_data[..copy_len].copy_from_slice(&payload[..copy_len]);
                    }
                }
            }
        }
    });

    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let tick_rate = Duration::from_secs_f64(1.0 / args.clock);
    let res = run_app(&mut terminal, state, args, tick_rate);

    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        println!("{err:?}");
    }

    Ok(())
}

fn marquee(text: &str, max_width: usize, tick: usize) -> String {
    let char_count = text.chars().count();
    if char_count <= max_width || max_width == 0 {
        return text.to_string();
    }

    let padded = format!("{}   *** ", text);
    let chars: Vec<char> = padded.chars().collect();
    let len = chars.len();
    let offset = tick % len;

    let mut result = String::with_capacity(max_width);
    for i in 0..max_width {
        result.push(chars[(offset + i) % len]);
    }
    result
}

fn run_app<B: Backend>(
    terminal: &mut Terminal<B>,
    state: Arc<Mutex<AppState>>,
    args: Args,
    tick_rate: Duration,
) -> Result<(), Box<dyn std::error::Error>>
where
    <B as Backend>::Error: 'static,
{
    let mut last_tick = Instant::now();
    let mut scroll_x: u16 = 0;
    let mut scroll_y: u16 = 0;
    let start_time = Instant::now();

    loop {
        terminal.draw(|f| {
            let term_area = f.area();

            // remember: each pixel is 2 chars
            let target_width = (args.width * 2 + 2) as u16;
            let target_height = (args.height + 2) as u16;

            let draw_area = ratatui::layout::Rect {
                x: term_area.x,
                y: term_area.y,
                width: target_width.min(term_area.width),
                height: target_height.min(term_area.height),
            };

            let elapsed_secs = start_time.elapsed().as_secs_f64();
            let marquee_tick = (elapsed_secs * 5.0) as usize;
            let available_width = draw_area.width.saturating_sub(2) as usize;

            let full_title = format!(" Esoteric Display Emulator - {} ", args.bind);
            let full_bottom = " press CTRL + C or q to stop ";

            let block = Block::default()
                .title(marquee(&full_title, available_width, marquee_tick))
                .title_alignment(Alignment::Center)
                .borders(Borders::ALL)
                .title_bottom(marquee(full_bottom, available_width, marquee_tick))
                .title_alignment(Alignment::Center);

            let data = {
                let lock = state.lock().unwrap();
                lock.frame_data.clone()
            };

            let mut lines = Vec::with_capacity(args.height);
            for y in 0..args.height {
                let mut spans = Vec::with_capacity(args.width);
                for x in 0..args.width {
                    if args.colors {
                        let idx = (y * args.width + x) * 3;
                        let r = *data.get(idx).unwrap_or(&0);
                        let g = *data.get(idx + 1).unwrap_or(&0);
                        let b = *data.get(idx + 2).unwrap_or(&0);
                        spans.push(Span::styled("██", Style::default().fg(Color::Rgb(r, g, b))));
                    } else {
                        let idx = y * args.width + x;
                        let val = *data.get(idx).unwrap_or(&0);
                        let chars = match val {
                            0..=5 => "  ",
                            6..=25 => "░░",
                            26..=50 => "▒▒",
                            51..=75 => "▓▓",
                            _ => "██",
                        };
                        spans.push(Span::raw(chars));
                    }
                }
                lines.push(Line::from(spans));
            }

            let paragraph = Paragraph::new(lines)
                .block(block)
                .scroll((scroll_y, scroll_x));

            f.render_widget(paragraph, draw_area);
        })?;

        let timeout = tick_rate
            .checked_sub(last_tick.elapsed())
            .unwrap_or_else(|| Duration::from_secs(0));

        if crossterm::event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') => return Ok(()),
                    KeyCode::Char('c') if key.modifiers.contains(event::KeyModifiers::CONTROL) => {
                        return Ok(());
                    }
                    KeyCode::Up => scroll_y = scroll_y.saturating_sub(1),
                    KeyCode::Down => scroll_y = scroll_y.saturating_add(1),
                    KeyCode::Left => scroll_x = scroll_x.saturating_sub(2),
                    KeyCode::Right => scroll_x = scroll_x.saturating_add(2),
                    _ => {}
                }
            }
        }
        if last_tick.elapsed() >= tick_rate {
            last_tick = Instant::now();
        }
    }
}
