# Ethan iOS (Flutter)

Flutter implementation of the Ethan Android application's navigation and visual hierarchy, connected to the Ethan `/api` backend.

## Run

```bash
cd app/ios
flutter pub get
flutter run -d ios
```

Configure the server address and access token on the login screen. The client validates `GET /api/health`, authenticates with `POST /api/auth`, and stores the URL/token locally using `shared_preferences`. Authenticated calls use `Authorization: Bearer <token>`.

## Development login

The app always opens the login screen. Its local server address and
`mock-token` are prefilled; press **登录 Ethan** to enter the home shell during
local development. `mock-token` only bypasses the initial authentication
check—every home screen request still uses the configured Ethan backend and
returns real server data or errors.

Implemented data paths include `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/{id}`, and streaming `POST /api/chat` (Server-Sent Events). Chat history is loaded from the selected session and assistant content is rendered incrementally as SSE events arrive.
