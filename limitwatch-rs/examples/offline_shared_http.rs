use anyhow::{ensure, Result};
use limitwatch::{
    providers::base::{HttpClient, HttpRequest},
    quota_client::SharedHttp,
};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Barrier,
    },
    thread,
    time::Duration,
};

fn serve(stream: TcpStream, requests: Arc<AtomicUsize>) -> Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            return Ok(());
        }
        loop {
            line.clear();
            reader.read_line(&mut line)?;
            if line == "\r\n" || line.is_empty() {
                break;
            }
        }
        requests.fetch_add(1, Ordering::SeqCst);
        writer.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\n{}")?;
        writer.flush()?;
    }
}

fn main() -> Result<()> {
    const WIDTH: usize = 6;
    let listener = TcpListener::bind("127.0.0.1:0")?;
    listener.set_nonblocking(true)?;
    let address = listener.local_addr()?;
    let accepts = Arc::new(AtomicUsize::new(0));
    let requests = Arc::new(AtomicUsize::new(0));
    let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let server = {
        let (accepts, requests, stop) = (accepts.clone(), requests.clone(), stop.clone());
        thread::spawn(move || {
            while !stop.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        accepts.fetch_add(1, Ordering::SeqCst);
                        let requests = requests.clone();
                        thread::spawn(move || {
                            let _ = serve(stream, requests);
                        });
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1))
                    }
                    Err(_) => break,
                }
            }
        })
    };
    let http = SharedHttp::new()?;
    for _ in 0..2 {
        let barrier = Arc::new(Barrier::new(WIDTH));
        let workers: Vec<_> = (0..WIDTH)
            .map(|_| {
                let (http, barrier) = (http.clone(), barrier.clone());
                thread::spawn(move || {
                    barrier.wait();
                    http.execute(HttpRequest {
                        method: "GET",
                        url: format!("http://{address}/quota"),
                        headers: BTreeMap::new(),
                        body: None,
                        timeout: Duration::from_secs(2),
                    })
                })
            })
            .collect();
        for worker in workers {
            ensure!(worker.join().expect("worker panicked")?.status == 200);
        }
    }
    stop.store(true, Ordering::SeqCst);
    server.join().expect("server panicked");
    ensure!(
        requests.load(Ordering::SeqCst) == WIDTH * 2,
        "request count mismatch"
    );
    ensure!(
        accepts.load(Ordering::SeqCst) <= WIDTH,
        "pool did not reuse connections"
    );
    println!(
        "shared-http: requests={} connections={} reused=true",
        WIDTH * 2,
        accepts.load(Ordering::SeqCst)
    );
    Ok(())
}
