# Ethan Android App

Native Android client for [Ethan Agent](https://github.com/ethan-agent/ethan-agent). Connects to your self-hosted backend via REST + SSE.

- **App name**: Ethan
- **Package**: `com.ethan.agent`
- **Min SDK**: 26 · **Target SDK**: 35
- **Stack**: Kotlin · Jetpack Compose · Material 3 · Hilt · Retrofit · OkHttp

See [PRD.md](./PRD.md) for the full product requirements document (Chinese).

## Quick Start

### Prerequisites

- Android SDK 35 (via Android Studio or `sdkmanager`)
- JDK 17+
- A running Ethan backend (`ethan serve` on port 8900)

### Build

```bash
cd app/android
export ANDROID_HOME=~/Library/Android/sdk   # adjust if needed
./gradlew assembleDebug
```

APK output: `app/build/outputs/apk/debug/app-debug.apk`

### Configure on Device

1. Install the APK
2. Enter server URL (e.g. `http://192.168.1.100:8900`)
3. Enter Access Token (from `~/.ethan/config.yaml` → `network.auth_token`)
4. Tap **登录**

## Project Structure

```
app/          → UI (Compose screens, ViewModels, Repository, DI)
core/model/   → Shared data classes (kotlinx.serialization)
core/network/ → Retrofit API service + SSE chat client
core/datastore/ → Server URL, token, theme preferences
```

## Features

| Screen | Description |
|--------|-------------|
| Chat | SSE streaming, tool timeline, consent dialog, attachments, quote reply |
| Sessions | Search, rename, delete, 3s poll refresh |
| Memory | Facts / Procedures tabs |
| Knowledge | CRUD + semantic/keyword search |
| Skills | View, create, edit, delete |
| Schedule | Pause/resume/delete jobs, open linked chat |
| Settings | Connection, agent, providers, channels, system prompts, profile, API keys |
| Docs | Built-in documentation reader |
| Logs | Backend/frontend log viewer |

## Open in Android Studio

File → Open → select `app/android/` directory.
