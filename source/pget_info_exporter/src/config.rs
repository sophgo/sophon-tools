use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::fs;
use tracing::{error, info};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    /// Exporter configuration
    pub exporter: ExporterConfig,

    /// Hardware monitoring configuration
    pub hardware: HardwareConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExporterConfig {
    /// Port to listen on
    pub port: u16,

    /// Host to bind to
    pub host: String,

    /// Metrics endpoint path
    pub metrics_path: String,

    /// Health check endpoint path
    pub health_path: String,

    /// Update interval in seconds
    pub update_interval_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareConfig {
    /// Temperature thresholds (Celsius)
    pub temperature_thresholds: TemperatureThresholds,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TemperatureThresholds {
    /// Critical temperature threshold
    pub critical: f64,

    /// Warning temperature threshold
    pub warning: f64,

    /// Normal temperature threshold
    pub normal: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabelConfig {
    pub name: String,
    pub value: String,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            exporter: ExporterConfig {
                port: 9090,
                host: "0.0.0.0".to_string(),
                metrics_path: "metrics".to_string(),
                health_path: "health".to_string(),
                update_interval_seconds: 15,
            },
            hardware: HardwareConfig {
                temperature_thresholds: TemperatureThresholds {
                    critical: 90.0,
                    warning: 85.0,
                    normal: 75.0,
                }
            }
        }
    }
}

impl Config {
    /// Load configuration from file
    pub async fn load<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn std::error::Error>> {
        let path = path.as_ref();

        if !path.exists() {
            info!("Configuration file not found at {:?}, using defaults", path);
            return Ok(Config::default());
        }

        let content = fs::read_to_string(path).await?;
        let config: Config = serde_yaml::from_str(&content)?;

        info!("Configuration loaded from {:?}", path);
        Ok(config)
    }

    /// Save configuration to file
    pub async fn save<P: AsRef<Path>>(&self, path: P) -> Result<(), Box<dyn std::error::Error>> {
        let path = path.as_ref();
        let content = serde_yaml::to_string(self)?;

        fs::write(path, content).await?;
        info!("Configuration saved to {:?}", path);

        Ok(())
    }

    /// Validate configuration
    pub fn validate(&self) -> Result<(), String> {
        // Validate port
        if self.exporter.port == 0 {
            return Err("Port cannot be 0".to_string());
        }

        // Validate update interval
        if self.exporter.update_interval_seconds == 0 {
            return Err("Update interval cannot be 0".to_string());
        }

        // Validate temperature thresholds
        if self.hardware.temperature_thresholds.critical <= self.hardware.temperature_thresholds.warning {
            return Err("Critical temperature must be greater than warning temperature".to_string());
        }

        if self.hardware.temperature_thresholds.warning <= self.hardware.temperature_thresholds.normal {
            return Err("Warning temperature must be greater than normal temperature".to_string());
        }

        Ok(())
    }
}
