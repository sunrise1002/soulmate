use std::{collections::VecDeque, fs, path::PathBuf, sync::Mutex};

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
const KEYRING_USER: &str = "openai-compatible-api-key";
const MAX_LOG_LINES: usize = 250;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredSettings {
    privacy_mode: String,
    provider: String,
    ollama_base_url: String,
    ollama_model: String,
    openai_base_url: String,
    openai_model: String,
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

#[derive(Default)]
struct ServiceState {
    process: Mutex<DaemonProcess>,
    logs: Mutex<VecDeque<String>>,
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

fn api_key_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|_| "The operating-system credential store is unavailable.".to_string())
}

fn stored_api_key() -> Option<String> {
    api_key_entry()
        .ok()
        .and_then(|entry| entry.get_password().ok())
        .filter(|value| !value.is_empty())
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
    let settings = load_stored_settings(app)?;
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|_| "The private data directory is unavailable.".to_string())?;
    fs::create_dir_all(&data_dir)
        .map_err(|_| "The private data directory could not be created.".to_string())?;

    let mut command = app
        .shell()
        .sidecar("decision-twin")
        .map_err(|_| "The packaged daemon sidecar is unavailable.".to_string())?
        .args(["serve"])
        .env("DATA_DIR", &data_dir)
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
        );
    if let Some(api_key) = stored_api_key() {
        command = command.env("SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY", api_key);
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
                            process.state = if payload.code == Some(0) {
                                "stopped".into()
                            } else {
                                "failed".into()
                            };
                            process.message = "The private local service exited.".into();
                        }
                    }
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
        let child = if let Ok(mut process) = state.process.lock() {
            let is_current = process
                .child
                .as_ref()
                .is_some_and(|child| child.pid() == pid);
            if is_current && process.state == "starting" {
                process.state = "failed".into();
                process.message = "The private local service did not become healthy.".into();
                process.child.take()
            } else {
                None
            }
        } else {
            None
        };
        if let Some(child) = child {
            let _ = child.kill();
        }
        push_log(&state, "daemon health check timed out".into());
    });
    current_status(&state)
}

fn stop_daemon_internal(state: &ServiceState) -> Result<ServiceStatus, String> {
    let child = {
        let mut process = state
            .process
            .lock()
            .map_err(|_| "The daemon process state is unavailable.".to_string())?;
        process.state = "stopped".into();
        process.message = "The private local service is stopped.".into();
        process.child.take()
    };
    if let Some(child) = child {
        child
            .kill()
            .map_err(|_| "The private local service could not be stopped.".to_string())?;
        push_log(state, "daemon stopped by desktop".into());
    }
    current_status(state)
}

#[tauri::command]
fn get_desktop_settings(app: AppHandle) -> Result<DesktopSettings, String> {
    load_stored_settings(&app).map(desktop_settings)
}

#[tauri::command]
fn save_desktop_settings(
    app: AppHandle,
    settings: DesktopSettingsInput,
) -> Result<DesktopSettings, String> {
    let stored = StoredSettings {
        privacy_mode: settings.privacy_mode,
        provider: settings.provider,
        ollama_base_url: settings.ollama_base_url,
        ollama_model: settings.ollama_model,
        openai_base_url: settings.openai_base_url,
        openai_model: settings.openai_model,
    };
    validate_settings(&stored)?;
    if settings.clear_api_key {
        let entry = api_key_entry()?;
        if entry.get_password().is_ok() {
            entry
                .delete_credential()
                .map_err(|_| "The saved provider credential could not be removed.".to_string())?;
        }
    }
    if let Some(api_key) = settings.api_key.filter(|value| !value.trim().is_empty()) {
        api_key_entry()?
            .set_password(api_key.trim())
            .map_err(|_| "The provider credential could not be saved securely.".to_string())?;
    }
    write_stored_settings(&app, &stored)?;
    Ok(desktop_settings(stored))
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
            save_desktop_settings,
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
    use super::{is_loopback, validate_settings, StoredSettings};
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
    fn loopback_detection_accepts_only_literal_local_hosts() {
        assert!(is_loopback(&Url::parse("http://127.0.0.1:11434").unwrap()));
        assert!(is_loopback(&Url::parse("http://[::1]:11434").unwrap()));
        assert!(!is_loopback(
            &Url::parse("https://127.0.0.1.example.test").unwrap()
        ));
    }
}
