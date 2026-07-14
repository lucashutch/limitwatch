use vergen_git2::{Emitter, Git2Builder};

fn main() {
    let git = Git2Builder::default()
        .describe(true, true, None)
        .build()
        .expect("configure Git version metadata");

    let mut emitter = Emitter::default();
    emitter.fail_on_error();
    if emitter
        .add_instructions(&git)
        .and_then(|emitter| emitter.emit())
        .is_err()
    {
        println!("cargo:warning=Git metadata unavailable; using Cargo package version");
        println!(
            "cargo:rustc-env=VERGEN_GIT_DESCRIBE={}",
            env!("CARGO_PKG_VERSION")
        );
    }
}
