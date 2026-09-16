use std::{
    collections::VecDeque,
    fs,
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    sync::{Condvar, Mutex},
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
use url::{Host, Url};

const API_ORIGIN: &str = "http://127.0.0.1:7432";
const KEYRING_SERVICE: &str = "app.soulmate.desktop";
const API_KEY_USER: &str = "openai-compatible-api-key";
const REMOTE_BACKUP_PASSPHRASE_USER: &str = "remote-backup-passphrase";
const REMOTE_BACKUP_ACCESS_KEY_USER: &str = "remote-backup-access-key-id";
const REMOTE_BACKUP_SECRET_KEY_USER: &str = "remote-backup-secret-access-key";
const MAX_LOG_LINES: usize = 250;
const DAEMON_SHUTDOWN_COMMAND: &[u8] = b"shutdown\n";
const DAEMON_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredRemoteBackupSettings {
    #[serde(default)]
    enabled: bool,
    #[serde(default)]
    automatic_daily: bool,
    #[serde(default = "default_remote_backup_interval")]
    interval_hours: u16,
    #[serde(default)]
    endpoint_url: String,
    #[serde(default = "default_remote_backup_region")]
    region: String,
    #[serde(default)]
    bucket: String,
    #[serde(default = "default_remote_backup_prefix")]
    prefix: String,
}

fn default_remote_backup_interval() -> u16 {
    24
}

fn default_remote_backup_region() -> String {
    "auto".into()
}

fn default_remote_backup_prefix() -> String {
    "soulmate".into()
}

impl Default for StoredRemoteBackupSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            automatic_daily: false,
            interval_hours: default_remote_backup_interval(),
            endpoint_url: String::new(),
            region: default_remote_backup_region(),
            bucket: String::new(),
            prefix: default_remote_backup_prefix(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredSettings {
    privacy_mode: String,
    provider: String,
    ollama_base_url: String,
    ollama_model: String,
    openai_base_url: String,
    openai_model: String,
    #[serde(default)]
    lan_enabled: bool,
    #[serde(default)]
    remote_backup: StoredRemoteBackupSettings,
}

impl Default for StoredSettings {
    fn default() -> Self {
        Self {
            privacy_mode: "strict_local".into(),
            provider: "ollama".into(),
            ollama_base_url: "http://127.0.0.1:11434".into(),
            ollama_model: String::new(),
            openai_base_url: "http://127.0.0.1:8000/v1".into(),
            openai_model: String::new(),
            lan_enabled: false,
            remote_backup: StoredRemoteBackupSettings::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopSettings {
    privacy_mode: String,
    provider: String,
    ollama_base_url: String,
    ollama_model: String,
    openai_base_url: String,
    openai_model: String,
    has_api_key: bool,
    lan_enabled: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopSettingsInput {
    privacy_mode: String,
    provider: String,
    ollama_base_url: String,
    ollama_model: String,
    openai_base_url: String,
    openai_model: String,
    api_key: Option<String>,
    clear_api_key: bool,
    #[serde(default)]
    lan_enabled: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RemoteBackupDesktopSettings {
    enabled: bool,
    automatic_daily: bool,
    interval_hours: u16,
    endpoint_url: String,
    region: String,
    bucket: String,
    prefix: String,
    has_passphrase: bool,
    has_access_key_id: bool,
    has_secret_access_key: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RemoteBackupDesktopSettingsInput {
    enabled: bool,
    automatic_daily: bool,
    interval_hours: u16,
    endpoint_url: String,
    region: String,
    bucket: String,
    prefix: String,
    passphrase: Option<String>,
    access_key_id: Option<String>,
    secret_access_key: Option<String>,
    clear_credentials: bool,
}

#[derive(Debug, Clone, Copy)]
struct RemoteBackupCredentialState {
    has_passphrase: bool,
    has_access_key_id: bool,
    has_secret_access_key: bool,
}

#[derive(Debug, Clone, Serialize)]
struct ServiceStatus {
    state: String,
    pid: Option<u32>,
    message: String,
}

struct DaemonProcess {
    child: Option<CommandChild>,
    state: String,
    message: String,
}

impl Default for DaemonProcess {
    fn default() -> Self {
        Self {
            child: None,
            state: "stopped".into(),
            message: "The private local service is stopped.".into(),
        }
    }
}

struct ServiceState {
    process: Mutex<DaemonProcess>,
    process_changed: Condvar,
    logs: Mutex<VecDeque<String>>,
}

impl Default for ServiceState {
    fn default() -> Self {
        Self {
            process: Mutex::new(DaemonProcess::default()),
            process_changed: Condvar::new(),
            logs: Mutex::new(VecDeque::new()),
        }
    }
}

#[derive(Debug, Deserialize)]
struct ApiRequest {
    method: String,
    path: String,
    body: Option<Value>,
}

#[derive(Debug, Serialize)]
struct ApiResponse {
    status: u16,
    body: Value,
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join("desktop-settings.json"))
        .map_err(|_| "Desktop configuration location is unavailable.".into())
}

fn load_stored_settings(app: &AppHandle) -> Result<StoredSettings, String> {
    let path = settings_path(app)?;
    if !path.exists() {
        return Ok(StoredSettings::default());
    }
    let content = fs::read_to_string(path)
        .map_err(|_| "Desktop configuration could not be read.".to_string())?;
    serde_json::from_str(&content)
        .map_err(|_| "Desktop configuration contains invalid data.".to_string())
}

fn write_stored_settings(app: &AppHandle, settings: &StoredSettings) -> Result<(), String> {
    let path = settings_path(app)?;
    let parent = path
        .parent()
        .ok_or_else(|| "Desktop configuration location is unavailable.".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|_| "Desktop configuration directory could not be created.".to_string())?;
    let temporary = path.with_extension("json.tmp");
    let content = serde_json::to_vec_pretty(settings)
        .map_err(|_| "Desktop configuration could not be encoded.".to_string())?;
    fs::write(&temporary, content)
        .map_err(|_| "Desktop configuration could not be saved.".to_string())?;
    fs::rename(temporary, path)
        .map_err(|_| "Desktop configuration could not be finalized.".to_string())
}

fn credential_entry(user: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, user)
        .map_err(|_| "The operating-system credential store is unavailable.".to_string())
}

fn stored_credential(user: &str) -> Option<String> {
    credential_entry(user)
        .ok()
        .and_then(|entry| entry.get_password().ok())
        .filter(|value| !value.is_empty())
}

fn stored_api_key() -> Option<String> {
    stored_credential(API_KEY_USER)
}

fn remote_backup_credential_state() -> RemoteBackupCredentialState {
    RemoteBackupCredentialState {
        has_passphrase: stored_credential(REMOTE_BACKUP_PASSPHRASE_USER).is_some(),
        has_access_key_id: stored_credential(REMOTE_BACKUP_ACCESS_KEY_USER).is_some(),
        has_secret_access_key: stored_credential(REMOTE_BACKUP_SECRET_KEY_USER).is_some(),
    }
}

fn remote_backup_desktop_settings(
    stored: StoredRemoteBackupSettings,
) -> RemoteBackupDesktopSettings {
    let credentials = remote_backup_credential_state();
    RemoteBackupDesktopSettings {
        enabled: stored.enabled,
        automatic_daily: stored.automatic_daily,
        interval_hours: stored.interval_hours,
        endpoint_url: stored.endpoint_url,
        region: stored.region,
        bucket: stored.bucket,
        prefix: stored.prefix,
        has_passphrase: credentials.has_passphrase,
        has_access_key_id: credentials.has_access_key_id,
        has_secret_access_key: credentials.has_secret_access_key,
    }
}

fn desktop_settings(stored: StoredSettings) -> DesktopSettings {
    DesktopSettings {
        privacy_mode: stored.privacy_mode,
        provider: stored.provider,
        ollama_base_url: stored.ollama_base_url,
        ollama_model: stored.ollama_model,
        openai_base_url: stored.openai_base_url,
        openai_model: stored.openai_model,
        has_api_key: stored_api_key().is_some(),
        lan_enabled: stored.lan_enabled,
    }
}

fn is_loopback(url: &Url) -> bool {
    match url.host() {
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        Some(Host::Domain(domain)) => domain.eq_ignore_ascii_case("localhost"),
        None => false,
    }
}

fn validate_settings(settings: &StoredSettings) -> Result<(), String> {
    if !matches!(
        settings.privacy_mode.as_str(),
        "strict_local" | "hybrid" | "offline"
    ) {
        return Err("Privacy mode is invalid.".into());
    }
    if !matches!(settings.provider.as_str(), "ollama" | "openai_compatible") {
        return Err("Model provider is invalid.".into());
    }
    let ollama = Url::parse(&settings.ollama_base_url)
        .map_err(|_| "The Ollama base URL is invalid.".to_string())?;
    let compatible = Url::parse(&settings.openai_base_url)
        .map_err(|_| "The OpenAI-compatible base URL is invalid.".to_string())?;
    if !is_loopback(&ollama) || ollama.scheme() != "http" {
        return Err("Ollama must use a loopback HTTP endpoint.".into());
    }
    let selected = if settings.provider == "ollama" {
        (&ollama, settings.ollama_model.trim())
    } else {
        (&compatible, settings.openai_model.trim())
    };
    if selected.1.is_empty() {
        return Err("The selected provider requires a model name.".into());
    }
    if settings.privacy_mode != "hybrid" && !is_loopback(selected.0) {
        return Err("Strict-local and offline modes require a loopback model endpoint.".into());
    }
    if !is_loopback(&compatible) && compatible.scheme() != "https" {
        return Err("External model endpoints must use HTTPS.".into());
    }
    Ok(())
}

fn validate_remote_backup_settings(
    settings: &StoredRemoteBackupSettings,
    privacy_mode: &str,
    credentials: RemoteBackupCredentialState,
) -> Result<(), String> {
    if !settings.enabled {
        return Ok(());
    }
    if !(1..=168).contains(&settings.interval_hours) {
        return Err("The backup interval must be between 1 and 168 hours.".into());
    }
    let endpoint = Url::parse(&settings.endpoint_url)
        .map_err(|_| "The S3-compatible endpoint URL is invalid.".to_string())?;
    if endpoint.host().is_none() || !matches!(endpoint.scheme(), "http" | "https") {
        return Err("The S3-compatible endpoint URL is invalid.".into());
    }
    if !is_loopback(&endpoint) && endpoint.scheme() != "https" {
        return Err("External backup endpoints must use HTTPS.".into());
    }
    if !is_loopback(&endpoint) && privacy_mode != "hybrid" {
        return Err("External backups require Hybrid privacy mode.".into());
    }
    if settings.bucket.trim().is_empty() {
        return Err("A backup bucket is required.".into());
    }
    if settings.region.trim().is_empty() {
        return Err("A signing region is required.".into());
    }
    if settings
        .prefix
        .split('/')
        .any(|part| matches!(part, "." | ".."))
    {
        return Err("The backup prefix cannot contain dot path segments.".into());
    }
    if !credentials.has_passphrase {
        return Err("An encryption passphrase of at least 12 characters is required.".into());
    }
    if !credentials.has_access_key_id || !credentials.has_secret_access_key {
        return Err("Both storage access keys are required.".into());
    }
    Ok(())
}

fn save_credential(user: &str, value: &str, label: &str) -> Result<(), String> {
    credential_entry(user)?
        .set_password(value)
        .map_err(|_| format!("The {label} could not be saved securely."))
}

fn remove_credential(user: &str, label: &str) -> Result<(), String> {
    let entry = credential_entry(user)?;
    if entry.get_password().is_ok() {
        entry
            .delete_credential()
            .map_err(|_| format!("The saved {label} could not be removed."))?;
    }
    Ok(())
}

fn push_log(state: &ServiceState, line: String) {
    if let Ok(mut logs) = state.logs.lock() {
        if logs.len() == MAX_LOG_LINES {
            logs.pop_front();
        }
        logs.push_back(line);
    }
}

fn current_status(state: &ServiceState) -> Result<ServiceStatus, String> {
    let process = state
        .process
        .lock()
        .map_err(|_| "The daemon process state is unavailable.".to_string())?;
    Ok(ServiceStatus {
        state: process.state.clone(),
        pid: process.child.as_ref().map(CommandChild::pid),
        message: process.message.clone(),
    })
}

fn port_in_use(address: SocketAddr) -> bool {
    TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok()
}

fn start_daemon_internal(app: &AppHandle) -> Result<ServiceStatus, String> {
    let state = app.state::<ServiceState>();
    let already_running = {
        let process = state
            .process
            .lock()
            .map_err(|_| "The daemon process state is unavailable.".to_string())?;
        process.child.is_some()
    };
    if already_running {
        return current_status(&state);
    }
    if port_in_use(SocketAddr::from(([127, 0, 0, 1], 7432))) {
        return Err(
            "Port 7432 is already in use. Stop the existing Soulmate daemon before starting the desktop service."
                .into(),
        );
    }
    let settings = load_stored_settings(app)?;
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|_| "The private data directory is unavailable.".to_string())?;
    fs::create_dir_all(&data_dir)
        .map_err(|_| "The private data directory could not be created.".to_string())?;

    let mut command = app
        .shell()
        .sidecar("soulmate")
        .map_err(|_| "The packaged daemon sidecar is unavailable.".to_string())?
        .args(["serve"])
        .env("DATA_DIR", &data_dir)
        .env("_SOULMATE_DESKTOP_MANAGED", "1")
        .env("SOULMATE_SERVER__HOST", "127.0.0.1")
        .env("SOULMATE_SERVER__PORT", "7432")
        .env("SOULMATE_PRIVACY__MODE", &settings.privacy_mode)
        .env("SOULMATE_LLM__PROVIDER", &settings.provider)
        .env("SOULMATE_LLM__OLLAMA__BASE_URL", &settings.ollama_base_url)
        .env("SOULMATE_LLM__OLLAMA__MODEL", &settings.ollama_model)
        .env(
            "SOULMATE_LLM__OPENAI_COMPATIBLE__BASE_URL",
            &settings.openai_base_url,
        )
        .env(
            "SOULMATE_LLM__OPENAI_COMPATIBLE__MODEL",
            &settings.openai_model,
        )
        // LAN exposure is opt-in; the daemon still binds loopback for this shell.
        .env(
            "SOULMATE_NETWORK__LAN_ENABLED",
            if settings.lan_enabled {
                "true"
            } else {
                "false"
            },
        );
    if let Some(api_key) = stored_api_key() {
        command = command.env("SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY", api_key);
    }
    command = command
        .env(
            "SOULMATE_REMOTE_BACKUP__BACKEND",
            if settings.remote_backup.enabled {
                "s3"
            } else {
                "disabled"
            },
        )
        .env(
            "SOULMATE_REMOTE_BACKUP__AUTOMATIC_DAILY",
            (settings.remote_backup.enabled && settings.remote_backup.automatic_daily).to_string(),
        )
        .env(
            "SOULMATE_REMOTE_BACKUP__INTERVAL_HOURS",
            settings.remote_backup.interval_hours.to_string(),
        );
    if settings.remote_backup.enabled {
        validate_remote_backup_settings(
            &settings.remote_backup,
            &settings.privacy_mode,
            remote_backup_credential_state(),
        )?;
        let passphrase = stored_credential(REMOTE_BACKUP_PASSPHRASE_USER)
            .ok_or_else(|| "The remote backup passphrase is unavailable.".to_string())?;
        let access_key_id = stored_credential(REMOTE_BACKUP_ACCESS_KEY_USER)
            .ok_or_else(|| "The remote backup access key is unavailable.".to_string())?;
        let secret_access_key = stored_credential(REMOTE_BACKUP_SECRET_KEY_USER)
            .ok_or_else(|| "The remote backup secret key is unavailable.".to_string())?;
        command = command
            .env(
                "SOULMATE_REMOTE_BACKUP__S3__ENDPOINT_URL",
                &settings.remote_backup.endpoint_url,
            )
            .env(
                "SOULMATE_REMOTE_BACKUP__S3__REGION",
                &settings.remote_backup.region,
            )
            .env(
                "SOULMATE_REMOTE_BACKUP__S3__BUCKET",
                &settings.remote_backup.bucket,
            )
            .env(
                "SOULMATE_REMOTE_BACKUP__S3__PREFIX",
                &settings.remote_backup.prefix,
            )
            .env("SOULMATE_REMOTE_BACKUP__PASSPHRASE", passphrase)
            .env("SOULMATE_REMOTE_BACKUP__S3__ACCESS_KEY_ID", access_key_id)
            .env(
                "SOULMATE_REMOTE_BACKUP__S3__SECRET_ACCESS_KEY",
                secret_access_key,
            );
    }
    let (mut receiver, child) = command
        .spawn()
        .map_err(|_| "The packaged daemon could not be started.".to_string())?;
    let pid = child.pid();
    {
        let mut process = state
            .process
            .lock()
            .map_err(|_| "The daemon process state is unavailable.".to_string())?;
        process.child = Some(child);
        process.state = "starting".into();
        process.message = "The private local service is starting.".into();
    }
    push_log(&state, format!("daemon started (pid {pid})"));
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = receiver.recv().await {
            let state = app_handle.state::<ServiceState>();
            match event {
                CommandEvent::Stdout(bytes) => {
                    push_log(&state, String::from_utf8_lossy(&bytes).trim().to_string());
                }
                CommandEvent::Stderr(bytes) => {
                    push_log(&state, String::from_utf8_lossy(&bytes).trim().to_string());
                }
                CommandEvent::Error(_) => {
                    push_log(&state, "daemon process reported an operating error".into());
                }
                CommandEvent::Terminated(payload) => {
                    if let Ok(mut process) = state.process.lock() {
                        let is_current = process
                            .child
                            .as_ref()
                            .is_some_and(|child| child.pid() == pid);
                        if is_current {
                            process.child = None;
                            if process.state != "failed" {
                                process.state = if payload.code == Some(0) {
                                    "stopped".into()
                                } else {
                                    "failed".into()
                                };
                                process.message = "The private local service exited.".into();
                            }
                        }
                    }
                    state.process_changed.notify_all();
                    push_log(
                        &state,
                        format!("daemon exited with code {:?}", payload.code),
                    );
                }
                _ => {}
            }
        }
    });
    let health_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let client = match reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_millis(500))
            .build()
        {
            Ok(client) => client,
            Err(_) => return,
        };
        for _ in 0..100 {
            if let Ok(response) = client.get(format!("{API_ORIGIN}/v1/health")).send().await {
                if response.status().is_success() {
                    let state = health_handle.state::<ServiceState>();
                    if let Ok(mut process) = state.process.lock() {
                        let is_current = process
                            .child
                            .as_ref()
                            .is_some_and(|child| child.pid() == pid);
                        if is_current && process.state == "starting" {
                            process.state = "running".into();
                            process.message =
                                "The private local service is running on this device.".into();
                        }
                    };
                    return;
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
        let state = health_handle.state::<ServiceState>();
        let shutdown_result = if let Ok(mut process) = state.process.lock() {
            let is_current = process
                .child
                .as_ref()
                .is_some_and(|child| child.pid() == pid);
            if is_current && process.state == "starting" {
                process.state = "failed".into();
                process.message = "The private local service did not become healthy.".into();
                Some(
                    process
                        .child
                        .as_mut()
                        .is_some_and(|child| child.write(DAEMON_SHUTDOWN_COMMAND).is_ok()),
                )
            } else {
                None
            }
        } else {
            Some(false)
        };
        if shutdown_result == Some(false) {
            push_log(
                &state,
                "daemon shutdown request failed after health timeout".into(),
            );
        }
        push_log(&state, "daemon health check timed out".into());
    });
    current_status(&state)
}

fn stop_daemon_internal(state: &ServiceState) -> Result<ServiceStatus, String> {
    let mut process = state
        .process
        .lock()
        .map_err(|_| "The daemon process state is unavailable.".to_string())?;
    let pid = if let Some(child) = process.child.as_mut() {
        let pid = child.pid();
        child
            .write(DAEMON_SHUTDOWN_COMMAND)
            .map_err(|_| "The private local service could not be asked to stop.".to_string())?;
        pid
    } else {
        process.state = "stopped".into();
        process.message = "The private local service is stopped.".into();
        return Ok(ServiceStatus {
            state: process.state.clone(),
            pid: None,
            message: process.message.clone(),
        });
    };
    process.state = "stopping".into();
    process.message = "The private local service is stopping.".into();
    push_log(state, "daemon shutdown requested by desktop".into());

    let deadline = Instant::now() + DAEMON_SHUTDOWN_TIMEOUT;
    while process
        .child
        .as_ref()
        .is_some_and(|child| child.pid() == pid)
    {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            process.state = "failed".into();
            process.message = "The private local service did not stop in time.".into();
            return Err(process.message.clone());
        }
        let (next, timeout) = state
            .process_changed
            .wait_timeout(process, remaining)
            .map_err(|_| "The daemon process state is unavailable.".to_string())?;
        process = next;
        if timeout.timed_out()
            && process
                .child
                .as_ref()
                .is_some_and(|child| child.pid() == pid)
        {
            process.state = "failed".into();
            process.message = "The private local service did not stop in time.".into();
            return Err(process.message.clone());
        }
    }
    process.state = "stopped".into();
    process.message = "The private local service is stopped.".into();
    Ok(ServiceStatus {
        state: process.state.clone(),
        pid: None,
        message: process.message.clone(),
    })
}

#[tauri::command]
fn get_desktop_settings(app: AppHandle) -> Result<DesktopSettings, String> {
    load_stored_settings(&app).map(desktop_settings)
}

#[tauri::command]
fn get_remote_backup_settings(app: AppHandle) -> Result<RemoteBackupDesktopSettings, String> {
    load_stored_settings(&app)
        .map(|settings| remote_backup_desktop_settings(settings.remote_backup))
}

#[tauri::command]
fn save_desktop_settings(
    app: AppHandle,
    settings: DesktopSettingsInput,
) -> Result<DesktopSettings, String> {
    let remote_backup = load_stored_settings(&app)?.remote_backup;
    let stored = StoredSettings {
        privacy_mode: settings.privacy_mode,
        provider: settings.provider,
        ollama_base_url: settings.ollama_base_url,
        ollama_model: settings.ollama_model,
        openai_base_url: settings.openai_base_url,
        openai_model: settings.openai_model,
        lan_enabled: settings.lan_enabled,
        remote_backup,
    };
    validate_settings(&stored)?;
    validate_remote_backup_settings(
        &stored.remote_backup,
        &stored.privacy_mode,
        remote_backup_credential_state(),
    )?;
    if settings.clear_api_key {
        remove_credential(API_KEY_USER, "provider credential")?;
    }
    if let Some(api_key) = settings.api_key.filter(|value| !value.trim().is_empty()) {
        save_credential(API_KEY_USER, api_key.trim(), "provider credential")?;
    }
    write_stored_settings(&app, &stored)?;
    Ok(desktop_settings(stored))
}

#[tauri::command]
fn save_remote_backup_settings(
    app: AppHandle,
    settings: RemoteBackupDesktopSettingsInput,
) -> Result<RemoteBackupDesktopSettings, String> {
    let passphrase = settings
        .passphrase
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let access_key_id = settings
        .access_key_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let secret_access_key = settings
        .secret_access_key
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if passphrase.is_some_and(|value| value.len() < 12) {
        return Err("The encryption passphrase must contain at least 12 characters.".into());
    }

    let existing = remote_backup_credential_state();
    let credentials = RemoteBackupCredentialState {
        has_passphrase: passphrase.is_some()
            || (!settings.clear_credentials && existing.has_passphrase),
        has_access_key_id: access_key_id.is_some()
            || (!settings.clear_credentials && existing.has_access_key_id),
        has_secret_access_key: secret_access_key.is_some()
            || (!settings.clear_credentials && existing.has_secret_access_key),
    };
    let remote_backup = StoredRemoteBackupSettings {
        enabled: settings.enabled,
        automatic_daily: settings.enabled && settings.automatic_daily,
        interval_hours: settings.interval_hours,
        endpoint_url: settings.endpoint_url.trim().into(),
        region: settings.region.trim().into(),
        bucket: settings.bucket.trim().into(),
        prefix: settings.prefix.trim().trim_matches('/').into(),
    };
    let mut stored = load_stored_settings(&app)?;
    if remote_backup.enabled {
        if let Ok(endpoint) = Url::parse(&remote_backup.endpoint_url) {
            if !is_loopback(&endpoint) {
                stored.privacy_mode = "hybrid".into();
            }
        }
    }
    validate_remote_backup_settings(&remote_backup, &stored.privacy_mode, credentials)?;

    if settings.clear_credentials {
        remove_credential(REMOTE_BACKUP_PASSPHRASE_USER, "backup passphrase")?;
        remove_credential(REMOTE_BACKUP_ACCESS_KEY_USER, "storage access key")?;
        remove_credential(REMOTE_BACKUP_SECRET_KEY_USER, "storage secret key")?;
    }
    if let Some(value) = passphrase {
        save_credential(REMOTE_BACKUP_PASSPHRASE_USER, value, "backup passphrase")?;
    }
    if let Some(value) = access_key_id {
        save_credential(REMOTE_BACKUP_ACCESS_KEY_USER, value, "storage access key")?;
    }
    if let Some(value) = secret_access_key {
        save_credential(REMOTE_BACKUP_SECRET_KEY_USER, value, "storage secret key")?;
    }
    stored.remote_backup = remote_backup.clone();
    write_stored_settings(&app, &stored)?;
    Ok(remote_backup_desktop_settings(remote_backup))
}

#[tauri::command]
fn daemon_status(state: State<'_, ServiceState>) -> Result<ServiceStatus, String> {
    current_status(&state)
}

#[tauri::command]
fn daemon_start(app: AppHandle) -> Result<ServiceStatus, String> {
    start_daemon_internal(&app)
}

#[tauri::command]
fn daemon_stop(state: State<'_, ServiceState>) -> Result<ServiceStatus, String> {
    stop_daemon_internal(&state)
}

#[tauri::command]
fn daemon_restart(app: AppHandle) -> Result<ServiceStatus, String> {
    stop_daemon_internal(&app.state::<ServiceState>())?;
    start_daemon_internal(&app)
}

#[tauri::command]
fn daemon_logs(state: State<'_, ServiceState>) -> Result<Vec<String>, String> {
    state
        .logs
        .lock()
        .map(|logs| logs.iter().cloned().collect())
        .map_err(|_| "Daemon logs are unavailable.".to_string())
}

#[tauri::command]
async fn api_request(request: ApiRequest) -> Result<ApiResponse, String> {
    if !request.path.starts_with("/v1/")
        || request.path.contains("..")
        || request.path.contains('?')
        || request.path.contains('#')
    {
        return Err("The local API path is not allowed.".into());
    }
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|_| "The private local service client is unavailable.".to_string())?;
    let url = format!("{API_ORIGIN}{}", request.path);
    let builder = match request.method.as_str() {
        "GET" => client.get(url),
        "POST" => client.post(url),
        "DELETE" => client.delete(url),
        _ => return Err("The local API method is not allowed.".into()),
    };
    let builder = match request.body {
        Some(Value::Null) | None => builder,
        Some(body) => builder.json(&body),
    };
    let response = builder
        .send()
        .await
        .map_err(|_| "The private local service is unavailable.".to_string())?;
    let status = response.status().as_u16();
    let body = response
        .json::<Value>()
        .await
        .map_err(|_| "The private local service returned an invalid response.".to_string())?;
    Ok(ApiResponse { status, body })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(ServiceState::default())
        .invoke_handler(tauri::generate_handler![
            api_request,
            daemon_logs,
            daemon_restart,
            daemon_start,
            daemon_status,
            daemon_stop,
            get_desktop_settings,
            get_remote_backup_settings,
            save_desktop_settings,
            save_remote_backup_settings,
        ])
        .setup(|app| {
            if let Err(error) = start_daemon_internal(app.handle()) {
                let state = app.state::<ServiceState>();
                if let Ok(mut process) = state.process.lock() {
                    process.state = "failed".into();
                    process.message = error;
                };
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Soulmate desktop application");

    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let _ = stop_daemon_internal(&handle.state::<ServiceState>());
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        desktop_settings, is_loopback, port_in_use, validate_remote_backup_settings,
        validate_settings, RemoteBackupCredentialState, StoredRemoteBackupSettings, StoredSettings,
    };
    use std::net::TcpListener;
    use url::Url;

    #[test]
    fn privacy_modes_reject_external_plaintext_and_local_mode_egress() {
        let mut settings = StoredSettings {
            provider: "openai_compatible".into(),
            openai_model: "model".into(),
            openai_base_url: "http://models.example.test/v1".into(),
            privacy_mode: "hybrid".into(),
            ..StoredSettings::default()
        };
        assert!(validate_settings(&settings).is_err());

        settings.openai_base_url = "https://models.example.test/v1".into();
        settings.privacy_mode = "strict_local".into();
        assert!(validate_settings(&settings).is_err());

        settings.privacy_mode = "hybrid".into();
        assert!(validate_settings(&settings).is_ok());
    }

    #[test]
    fn access_from_other_devices_is_off_until_the_owner_enables_it() {
        let defaults = StoredSettings::default();
        assert!(!defaults.lan_enabled);
        assert!(!desktop_settings(defaults).lan_enabled);

        let enabled = StoredSettings {
            ollama_model: "model".into(),
            lan_enabled: true,
            ..StoredSettings::default()
        };
        assert!(validate_settings(&enabled).is_ok());
        assert!(desktop_settings(enabled).lan_enabled);
    }

    #[test]
    fn stored_settings_without_a_network_section_stay_loopback_only() {
        let stored: StoredSettings = serde_json::from_str(
            r#"{"privacyMode":"strict_local","provider":"ollama","ollamaBaseUrl":"http://127.0.0.1:11434","ollamaModel":"model","openaiBaseUrl":"http://127.0.0.1:8000/v1","openaiModel":""}"#,
        )
        .expect("settings saved before Phase 7 must still load");
        assert!(!stored.lan_enabled);
        assert!(!stored.remote_backup.enabled);
        assert_eq!(stored.remote_backup.interval_hours, 24);
    }

    #[test]
    fn loopback_detection_accepts_only_literal_local_hosts() {
        assert!(is_loopback(&Url::parse("http://127.0.0.1:11434").unwrap()));
        assert!(is_loopback(&Url::parse("http://[::1]:11434").unwrap()));
        assert!(!is_loopback(
            &Url::parse("https://127.0.0.1.example.test").unwrap()
        ));
    }

    #[test]
    fn occupied_port_is_detected_before_a_sidecar_is_started() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("test listener must bind");
        let address = listener
            .local_addr()
            .expect("test listener must have an address");

        assert!(port_in_use(address));
    }

    #[test]
    fn external_remote_backup_requires_hybrid_mode_and_complete_credentials() {
        let settings = StoredRemoteBackupSettings {
            enabled: true,
            automatic_daily: true,
            endpoint_url: "https://account.r2.cloudflarestorage.com".into(),
            bucket: "soulmate-backups".into(),
            ..StoredRemoteBackupSettings::default()
        };
        let complete = RemoteBackupCredentialState {
            has_passphrase: true,
            has_access_key_id: true,
            has_secret_access_key: true,
        };
        assert!(validate_remote_backup_settings(&settings, "strict_local", complete).is_err());
        assert!(validate_remote_backup_settings(&settings, "hybrid", complete).is_ok());

        let missing_secret = RemoteBackupCredentialState {
            has_secret_access_key: false,
            ..complete
        };
        assert!(validate_remote_backup_settings(&settings, "hybrid", missing_secret).is_err());
    }

    #[test]
    fn disabled_remote_backup_keeps_the_local_only_default() {
        assert!(validate_remote_backup_settings(
            &StoredRemoteBackupSettings::default(),
            "strict_local",
            RemoteBackupCredentialState {
                has_passphrase: false,
                has_access_key_id: false,
                has_secret_access_key: false,
            },
        )
        .is_ok());
    }
}
