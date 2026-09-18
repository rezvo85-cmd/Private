# RONN Native Mobile

This is the native Expo/React Native shell for RONN. It talks to the same RONN Core backend as the web app but uses native iOS/Android scrolling, keyboard handling, and text input instead of Safari/PWA viewport behavior.

## Run
```
npm install
npx expo start
```

The app uses the existing Owner Access flow and stores the returned owner session in Expo SecureStore. The RONN backend remains on Render, so mobile and desktop share the same brain.

Building a standalone iPhone app still requires Apple signing / an Expo EAS or Xcode build.
