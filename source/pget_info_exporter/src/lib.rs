pub mod chip;
pub mod config;
pub mod exporter;
pub mod hardware;
pub mod metrics;
// pub mod sysfs;

use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON parsing error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("YAML parsing error: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("Hardware detection error: {0}")]
    Hardware(String),

    #[error("Metrics error: {0}")]
    Metrics(String),
}

pub type Result<T> = std::result::Result<T, Error>;
