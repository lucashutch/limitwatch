fn main() {
    if let Err(error) = limitwatch::cli::run() {
        eprintln!("Error: {error:#}");
        std::process::exit(1);
    }
}
