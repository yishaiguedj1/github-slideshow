# Android Platform Mechanisms and Restrictions for Call Recording Without Root (Android 9 to 16, Android 17 previews), as of Oct 2026

Research notes. Sources were checked on 2026-10-22. Primary sources were developer.android.com docs, the AOSP manifests (via the GitHub aosp-mirror), and the source code of open-source recorders (BCR, ShizuCallRecorder, which I cloned and grepped). Some sites were unreachable from the research environment (xda-developers.com, nllapps.com, cubeacr.app, shizuku.rikka.app, thehackernews.com, android.googlesource.com). For those I relied on search-result summaries and say so.

## 1. History of the platform blocks (Android 9 to 11+) and the CAPTURE_AUDIO_OUTPUT protection level

### Takeaway
Android 9 cut background apps off from the microphone and closed the trick that recorders had used through 8.1. Android 10 brought the concurrent-capture policy, under which a normal app gets silence while a call is active. The real call streams (VOICE_CALL/UPLINK/DOWNLINK) are gated by CAPTURE_AUDIO_OUTPUT, which is `signature|privileged|role` and cannot be granted to a normal third-party app.

### Cited Findings
- **Android 9:** the platform states: "If your app is running in the background on a device running Android 9 … Your app cannot access the microphone or camera… use a foreground service." — [Android 9 behavior changes](https://developer.android.com/about/versions/pie/android-9.0-changes-all)
- **Android 9:** reading phone numbers in `PHONE_STATE` broadcasts and `onCallStateChanged()` now also requires `READ_CALL_LOG` (new CALL_LOG permission group). This matters to recorders that name files after the caller. — [Android 9 behavior changes](https://developer.android.com/about/versions/pie/android-9.0-changes-all)
- **Android 9 (developer reports):** recorder developers said the workaround that "worked up until Android 8.1" was closed on Android 9, and "root is the only way to go". Some sources say only earpiece/loudspeaker (acoustic) recording remained. — [PiunikaWeb 2018](https://piunikaweb.com/2018/08/14/android9pie-closes-all-doors-to-call-recording-sans-root-say-third-party-app-devs/); [XDA](https://www.xda-developers.com/android-pie-blocks-non-root-call-recording-apps/) (search summary only, site unreachable); [PhoneArena](https://www.phonearena.com/news/no-call-recording-support-android-9-pie-phone-root-problem-fixed_id107792)
- **Before Android 10 (first come, first served):** under this policy, a second app's `AudioRecord.startRecording()` returned an error, except a privileged app with `CAPTURE_AUDIO_HOTWORD` using the HOTWORD source. — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Android 10 concurrent-capture policy:** "Two ordinary apps can never capture audio at the same time." "Privileged apps have higher priority than ordinary apps." `CAMCORDER` and `VOICE_COMMUNICATION` are privacy-sensitive sources. — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Android 10, voice call + ordinary app:** a call is active when `AudioManager.getMode()` is `MODE_IN_CALL` or `MODE_IN_COMMUNICATION`. Under this rule:
  - "The call always receives audio."
  - "The app can capture audio if it is an accessibility service."
  - "The app can capture the voice call if it is a privileged (pre-installed) app with permission CAPTURE_AUDIO_OUTPUT. To capture the call, the app must use VOICE_UPLINK and/or VOICE_DOWNLINK sources, and/or the AudioDeviceInfo.TYPE_TELEPHONY device."
  — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Android 11:** `setPrivacySensitive(true)` makes a capture private, so "even a privileged Assistant cannot capture concurrently". `VOICE_COMMUNICATION` is private by default but `UNPROCESSED` is not. The APIs are `AudioRecord.Builder.setPrivacySensitive()`, `MediaRecorder.setPrivacySensitive()` and the AAudio equivalents. — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Silence detection:** a silenced client keeps receiving zeros rather than an error. Apps detect this with `AudioRecord.registerAudioRecordingCallback()`, which must be registered before `startRecording()`, and `AudioRecordingConfiguration.isClientSilenced()`. — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **AOSP permission definition:** the current definition in `frameworks/base/core/res/AndroidManifest.xml` is `<permission android:name="android.permission.CAPTURE_AUDIO_OUTPUT" android:protectionLevel="signature|privileged|role" />`, with the comment "Not for use by third-party applications." — [AOSP core manifest (aosp-mirror)](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/core/res/AndroidManifest.xml)
- **AOSP Shell package:** the Shell package (UID 2000, the ADB shell) declares `RECORD_AUDIO`, `CAPTURE_AUDIO_OUTPUT`, `MODIFY_AUDIO_ROUTING`, `CAPTURE_MEDIA_OUTPUT` and `CAPTURE_VOICE_COMMUNICATION_OUTPUT`. This is why ADB/Shizuku-based recording works. — [AOSP Shell AndroidManifest.xml](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/packages/Shell/AndroidManifest.xml)

### Inferences
- The source mirror shows `CAPTURE_AUDIO_OUTPUT` is also grantable via a *role* (`|role`), but no role available to third-party apps (dialer, screening, assistant) is documented as carrying it. Being the default dialer does not unlock it (see section 4).
- Android 9 was the "kill switch" for the background-mic method and for raw VOICE_CALL access by user apps. Android 10 then formalised silencing during calls. After Android 10, normal no-root apps have only three ways to get the remote party: (a) an accessibility service (or the assistant role), (b) acoustic leakage via speakerphone into the mic, or (c) borrowing shell (ADB) privileges.

### Gaps
- I could not reach android.googlesource.com from the research environment, so I did not verify the exact AudioPolicyService.cpp logic. That includes the accessibility-UID handling and `canCaptureOutput` checks, and the specific Android 9 commit that tightened `AUDIO_SOURCE_VOICE_CALL` checks. The descriptions above come from the official developer doc.
- I found no primary source on exactly which version first added `CAPTURE_AUDIO_OUTPUT` to the Shell manifest. ShizuCallRecorder's code comments say it works from Android 11 (see section 3).

## 2. Which audio sources capture the remote party, and why the accessibility trick works

### Takeaway
Only VOICE_CALL/VOICE_UPLINK/VOICE_DOWNLINK (or the TYPE_TELEPHONY device) give a true digital tap of both sides. All of them need CAPTURE_AUDIO_OUTPUT. The mic-type sources (MIC, CAMCORDER, VOICE_RECOGNITION, VOICE_COMMUNICATION, UNPROCESSED) record the local mic only. The remote party appears there only through speaker leakage, and device echo cancellation often removes it. The accessibility trick works because the Android 10+ policy explicitly exempts accessibility services from call-time silencing. It does not give access to the downlink stream.

### Cited Findings
- **Accessibility exemption:** under the official concurrent-capture policy, during a voice call "The app can capture audio if it is an accessibility service". Accessibility services and `ROLE_ASSISTANT` holders count as "privileged apps". — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Accessibility + ordinary app:** "If the service's UI is on top, both the service and the app receive audio input". Otherwise it is treated like two ordinary apps. The service must meet the "strict AccessibilityService declaration requirements". — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Assistant:** "The Assistant can receive audio (no matter whether it's in the foreground or background) unless another app using a privacy-sensitive audio source is already capturing." — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **BCR:** BCR records the `VOICE_CALL` stream and says this stream, along with `VOICE_DOWNLINK` and `VOICE_UPLINK`, "cannot be accessed without this system permission" (CAPTURE_AUDIO_OUTPUT). This is why BCR must be installed as a system app on rooted devices or custom firmware. Unrooted stock firmware is an explicit non-feature. — [BCR README](https://github.com/chenxiaolong/BCR)
- **BCR permissions:** BCR also needs user-granted `RECORD_AUDIO`, plus `CONTROL_INCALL_EXPERIENCE` (also system-granted) to monitor call state. — [BCR README](https://github.com/chenxiaolong/BCR)
- **BCR stereo:** stereo with separate uplink/downlink channels "is only known to work on Pixel devices running newer versions of Android". Other devices may give no separation or no audio at all. — [BCR README](https://github.com/chenxiaolong/BCR)
- **ShizuCallRecorder source options:** the user can pick `VOICE_CALL`, `VOICE_UPLINK`, `VOICE_DOWNLINK`, `VOICE_COMMUNICATION` (mic) and `VOICE_RECOGNITION` (mic), among others. — [ShizuCallRecorder `RecordingPlanResolver.kt`](https://github.com/kitsumed/ShizuCallRecorder)
- **ShizuCallRecorder privacy flag:** for the mic-class sources (MIC, CAMCORDER, VOICE_RECOGNITION, VOICE_COMMUNICATION, UNPROCESSED, VOICE_PERFORMANCE) it calls `setPrivacySensitive(false)` so the capture is not marked private. — [ShizuCallRecorder `AudioRecordCapture.kt`, `ShellWorkarounds.kt`](https://github.com/kitsumed/ShizuCallRecorder)
- **ShizuCallRecorder code comment** on how shell privileges avoid silencing: "Normal apps would hit this when capturing VOICE_COM during call. However (Android 11+), we run with the shell UID (2000) and have CAPTURE_AUDIO_OUTPUT permission, which allows us to bypass this restriction." — [ShizuCallRecorder `AudioRecordCapture.kt`](https://github.com/kitsumed/ShizuCallRecorder)
- **Cube ACR:** the Play version "can no longer request the accessibility connector". Cube describes the connector as essential for "recording interlocutor's voice during mobile calls on Android 10 and up". Users report the other party is inaudible on some phones and fall back to speakerphone. — [Cube ACR Helper page](https://cubeacr.app/helper.html) (search summary only, site unreachable); [Yahoo Tech](https://tech.yahoo.com/articles/google-makes-difficult-record-calls-155834200.html)
- **Play policy:** Google changed its Play developer policy in 2022 (effective May 2022) to forbid Play apps from using accessibility services for call recording. — [Yahoo Tech](https://tech.yahoo.com/articles/google-makes-difficult-record-calls-155834200.html)

### Inferences
- **What the accessibility trick does and does not do.** It only stops the silencing of a *mic-class* `AudioRecord` (usually `VOICE_RECOGNITION`, `MIC` or `VOICE_COMMUNICATION`) during `MODE_IN_CALL`. The remote voice is captured acoustically from the earpiece or speaker.
  - On many devices it is barely audible unless speakerphone is on or volume is high, because the modem/DSP's echo canceller subtracts the downlink from the mic path.
  - `VOICE_RECOGNITION` or `UNPROCESSED`, which normally skip AEC/NS, generally preserve more of the far-end leakage than `VOICE_COMMUNICATION`.
  - This is consistent with the "inaudible on some phones" reports. It is not verified per device.
- **Minimal code for the accessibility approach** (based on the documented policy, not on any single app):
  - Declare an `AccessibilityService` with `BIND_ACCESSIBILITY_SERVICE`.
  - Start capture from that service's process: `AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000/48000, CHANNEL_IN_MONO, ENCODING_PCM_16BIT, buf)`.
  - Register `registerAudioRecordingCallback` and check `isClientSilenced` to detect failure.

### Gaps
- I found no authoritative per-OEM matrix of which mic sources capture the far end. OEM-specific behaviour is anecdotal: Samsung/Xiaomi ship native recorders, and some OEM firmwares historically exposed VOICE_CALL to normal apps.
- I could not verify the exact AudioPolicyService code path that identifies accessibility UIDs (`setA11yServicesUids`), because AOSP gitiles was unreachable.

## 3. Shizuku / wireless ADB approach (Android 11+)

### Takeaway
This is the only no-root way to get the true VOICE_CALL/UPLINK/DOWNLINK streams on stock firmware. The recorder runs code inside a process with the shell UID (2000), which holds CAPTURE_AUDIO_OUTPUT and CAPTURE_VOICE_COMMUNICATION_OUTPUT. The open-source reference is ShizuCallRecorder: Android 12 to 16 supported, Android 11 limited, Android 17 unknown. The cost is setup complexity and re-activation after reboot.

### Cited Findings
- **What it is:** ShizuCallRecorder is "the first non-root FOSS call recorder for Android 11+". It "empowers ADB through Shizuku to use an advanced list of permissions given to the shell application". — [ShizuCallRecorder GitHub](https://github.com/kitsumed/ShizuCallRecorder); [F-Droid listing](https://f-droid.org/de/packages/com.kitsumed.shizucallrecorder); [IzzyOnDroid](https://apt.izzysoft.de/packages/com.kitsumed.shizucallrecorder)
- **Features:**
  - Records both sides, with optional "Separate uplink and downlink audio" in stereo.
  - Works with Bluetooth or a remote headset.
  - "runs only on phone event changes, no persistent background process and notifications".
  - Codecs: Opus, AAC, HE-AAC v1 and others.
  — [ShizuCallRecorder README](https://github.com/kitsumed/ShizuCallRecorder)
- **Tested versions:**

  | Android | Status |
  |---|---|
  | 11 | Limited: "Unlocked screen required", otherwise it crashes |
  | 12–16 | Yes |
  | 17 | Unknown: "not yet released, with major ADB changes" |

  The README says the app uses hidden APIs and is "prone to breaking in new Android releases or due to specific OEM modifications". The Requirements section says Android 12+ while the header says 11+. — [ShizuCallRecorder README](https://github.com/kitsumed/ShizuCallRecorder)
- **Code-level mechanism** (from the cloned source):
  - `ShellWorkarounds.kt` is "inspired by scrcpy shell workarounds". It builds a fake `ActivityThread`/`Context` so framework APIs work inside the shell process.
  - It constructs `AudioRecord` via reflection (`audioParamCheck`, the native setup) with `SAMPLE_RATE = 16_000`, mono, PCM 16-bit.
  - `ShellCommandExecutor.kt` grants AppOps to the app via `appops set --user <id> <pkg> <op> allow`, for example `android:manage_ongoing_calls` for call detection.
  — [ShizuCallRecorder source](https://github.com/kitsumed/ShizuCallRecorder)
- **VoIP / Wi-Fi calls (Android 14+):** the app uses a *dynamic audio policy* (`android.media.audiopolicy.AudioMixingRule` with `MIX_ROLE_PLAYERS`, `RULE_MATCH_ATTRIBUTE_USAGE` on `USAGE_VOICE_COMMUNICATION`). The code comment says this "require[s] shell to have the CAPTURE_VOICE_COMMUNICATION_OUTPUT permission". — [ShizuCallRecorder `AudioPlaybackCapture.kt`](https://github.com/kitsumed/ShizuCallRecorder)
- **Sample-rate cap:** the code comment says "Some Android native API enforces a maximum of 16 kHz when capture is defined with system level access/high-priority capture… 16 kHz… known as HD voice quality". It cites AOSP Android 16 `audio_policy_configuration.xml` and `Engine.cpp`. — [ShizuCallRecorder `AudioConfig.kt`](https://github.com/kitsumed/ShizuCallRecorder)
- **Setup and persistence:**
  - Install Shizuku; the author recommends the thedjchi fork.
  - Enable "Auto-Disable USB Debugging".
  - TCP mode (port 5555 or another) lets Shizuku start without Wi-Fi but "adds security risk".
  - Two modes:
    - **Method 1:** always-on Shizuku with "Start on Boot" (required), optional Watchdog and TCP mode. Not recommended for general users.
    - **Method 2 (recommended):** "Manage Shizuku". The app starts Shizuku via an intent auth key, optionally "only when recording".
  — [ShizuCallRecorder configuration.md](https://github.com/kitsumed/ShizuCallRecorder) (docs/configuration.md)
- **Persistence (Shizuku):** Shizuku setup requires re-enabling wireless debugging after each reboot. — [search summary of ghisler.com Shizuku page](https://www.ghisler.com/shizuku.htm)
- **Known failures:**
  - Some Chinese OEMs (Xiaomi, Vivo) revert AppOps changes ("steps exhausted" error). The manual fix is `adb shell appops set --user 0 com.kitsumed.shizucallrecorder android:manage_ongoing_calls allow`.
  - Aggressive battery killers; dontkillmyapp is recommended.
  - VoIP/Wi-Fi calls can give silent or one-sided audio. On Android ≤12 the suggestion is to disable Wi-Fi Calling.
  — [ShizuCallRecorder troubleshooting.md](https://github.com/kitsumed/ShizuCallRecorder)
- **Android 17 ADB:** Android 17 introduces "ADB Wi-Fi 2.0", a new Rust implementation that auto-reconnects to trusted networks. No source confirms whether this helps or breaks Shizuku. — [Android Authority](https://www.androidauthority.com/android-17-adb-wi-fi-2-0-3678411/)

### Inferences
- **What users go through:** about 5 to 10 minutes of first-time setup. The steps are developer options, wireless debugging pairing via a notification code, and starting Shizuku. After each reboot the user re-starts Shizuku over wireless debugging, which needs Wi-Fi, unless they use TCP mode or the thedjchi fork's start-on-boot.
- **Two architectures:** a recorder can either (a) run its recording code *inside* the shell process via Shizuku `UserService` (ShizuCallRecorder's approach), or (b) only use shell to run `pm grant`/`appops`. Option (b) cannot grant `CAPTURE_AUDIO_OUTPUT` to a normal app, because it is not a runtime/development permission. That is why (a) is required. This inference follows from the `signature|privileged|role` protection level, and I did not test it.

### Gaps
- I could not reach shizuku.rikka.app. The official Shizuku docs on start-on-boot limits and Android 11 wireless pairing were therefore not verified directly.
- I found no measured data on how many users complete setup, and no confirmation of Android 17 stable compatibility.

## 4. Default dialer role, InCallService, call screening

### Takeaway
Holding ROLE_DIALER or the call-screening role does **not** grant CAPTURE_AUDIO_OUTPUT or unlock VOICE_CALL. It mainly gives call-state awareness (InCallService), and it qualifies the app for the `phoneCall` FGS type. It is also on Android 15's restricted-settings list for sideloaded apps.

### Cited Findings
- **`phoneCall` FGS prerequisite:** the app declares `MANAGE_OWN_CALLS` *or* "is the default dialer app through the ROLE_DIALER role". Its stated purpose is to "Continue an ongoing call using the ConnectionService APIs". The docs point screening use cases to `CallScreeningService`. — [FGS types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- **Restricted roles:** Android 15 compatibility requirements put the dialer and SMS default roles among the restricted settings for sideloaded apps. — [Android Authority](https://androidauthority.com/android-15-restricted-settings-sideloading-3481098); [9to5Google](https://9to5google.com/2024/09/12/android-15-sideloaded-apps-restrictions/)
- **Accessibility as a privileged class:** the official concurrent-capture policy lists only accessibility services, the Assistant role and pre-installed apps with CAPTURE_AUDIO_OUTPUT as privileged. It does not list the dialer role. — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)

### Inferences
- A third-party dialer's InCallService gives the exact call start/end, number and direction. With a `phoneCall`/`microphone` FGS, the app can keep the mic open, but the mic is still silenced during the call by the concurrent-capture policy. Only an accessibility service or shell privileges avoid that silencing.
- Being the Assistant (ROLE_ASSISTANT) is listed as privileged, but the policy only describes it sharing mic input. Whether the Assistant receives non-silenced audio during `MODE_IN_CALL` is not documented, and it would still be mic-only.

### Gaps
- I found no official statement explicitly saying "the dialer role does not enable recording". That conclusion is inferred from the permission and policy docs above.

## 5. Foreground service types and background-start restrictions (Android 14/15/16)

### Takeaway
On Android 14+, a `microphone` FGS cannot be created while the app is in the background. It also cannot be started from BOOT_COMPLETED, and on Android 15 `phoneCall` cannot either. A recorder must therefore start the FGS through an exemption. Typical exemptions are a notification/widget tap, a PendingIntent from a visible app, or binding by a system component. Accessibility services and InCallService/CallScreeningService are system-bound, which is how recorders get around this.

### Cited Findings
- **Microphone FGS:** requires `FOREGROUND_SERVICE_MICROPHONE`, `foregroundServiceType="microphone"` and `RECORD_AUDIO` granted. `RECORD_AUDIO` "is subject to while-in-use restrictions… you cannot create a microphone foreground service while your app is in the background and you cannot launch a microphone foreground service from a BOOT_COMPLETED receiver, with a few exceptions." — [FGS types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- **Background creation on Android 14+:** "if your app is in the background, and it tries to create a foreground service of type camera, location, or microphone… throws a SecurityException". This holds "even if the app falls into one of the exemptions from background start restrictions". `checkSelfPermission()` misleadingly returns GRANTED in the background. — [FGS background-start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- **While-in-use exemptions:**
  - service started by a system component;
  - app widget interaction;
  - notification interaction;
  - a `PendingIntent` from a different visible app;
  - device owner DPC;
  - the app provides the `VoiceInteractionService`;
  - the app holds `START_ACTIVITIES_FROM_BACKGROUND`.
  
  Accessibility is not mentioned explicitly. The Logcat signature is "Foreground service started from background can not have location/camera/microphone access". — [FGS background-start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- **Android 15:**
  - `BOOT_COMPLETED` receivers may not launch the `dataSync`, `camera`, `mediaPlayback`, `phoneCall`, `mediaProjection` or `microphone` FGS types ("since Android 14" for microphone). The result is `ForegroundServiceStartNotAllowedException`.
  - Test with `adb shell am compat enable FGS_BOOT_COMPLETED_RESTRICTIONS <pkg>`.
  - The `SYSTEM_ALERT_WINDOW` exemption now requires a *visible* `TYPE_APPLICATION_OVERLAY` window.
  - Apps must be top or running an FGS to request audio focus.
  — [Android 15 behavior changes](https://developer.android.com/about/versions/15/behavior-changes-15)
- **`phoneCall` FGS on Android 15:** "Apps that target Android 15 or higher are not allowed to launch a phone call foreground service from a BOOT_COMPLETED broadcast receiver." — [FGS types](https://developer.android.com/develop/background-work/services/fgs/service-types)

### Inferences
- **Accessibility services:** the system binds them, so they run as a persistent bound service and are counted as privileged for capture. In practice they can start a microphone FGS or record directly while the app has no visible UI. This most likely works through the "started by a system component" path. Not stated verbatim by Google.
- **ShizuCallRecorder:** it sidesteps FGS rules entirely by recording in the Shizuku shell process, which is not subject to app FGS policy. This matches its "no persistent background process and notifications" claim.
- **Practical pattern for no-root apps on Android 14+:**
  - Use `CallScreeningService` or InCallService (system-bound) or an accessibility service as the call trigger.
  - Start `startForeground(..., FOREGROUND_SERVICE_TYPE_MICROPHONE)` from that bound context.
  - Do not start from a `PHONE_STATE` broadcast receiver, which is background and fails on Android 14+.

### Gaps
- I found no official doc listing accessibility-service-originated FGS starts as a while-in-use exemption. There were no Android 16-specific FGS microphone changes in the sources I reached.

## 6. Restricted settings (Android 13+), Enhanced Confirmation Mode (Android 15), Android 16/17, Advanced Protection

### Takeaway
Sideloaded APKs, which is how accessibility-based recorders are distributed after the Play ban, hit "restricted settings". Since Android 13 the user must manually allow them per app in App info. Android 15 widened this via Enhanced Confirmation Mode (ECM), which covers more permissions and closes the session-installer loophole. Android 17 Advanced Protection mode revokes accessibility from any app not flagged `isAccessibilityTool`, which kills the accessibility recording method for users who enable it.

### Cited Findings
- **Android 15 restricted list:** accessibility, notification listener, device admin, display over other apps, usage access, the dialer and SMS default roles, and runtime SMS permission. Users can still manually allow these per app.
- **ECM purpose:** closes abuse of the session-based install API, which was used to look like a store install. It targets banking trojans that abuse accessibility.
  — [Android Authority](https://androidauthority.com/android-15-restricted-settings-sideloading-3481098); [9to5Google](https://9to5google.com/2024/09/12/android-15-sideloaded-apps-restrictions/); [The Hacker News 2024](https://thehackernews.com/2024/05/android-15-introduces-new-features-to.html?m=1)
- **Android 17 Advanced Protection (AAPM):**
  - Introduced in Android 17 Beta 2 (March 2026). Prevents apps that are not flagged accessibility tools (`isAccessibilityTool`) from using the accessibility API.
  - Existing grants are revoked automatically when AAPM is enabled, and cannot be re-granted until AAPM is turned off.
  - Screen readers, switch access, voice control and Braille tools are exempt.
  — [The Hacker News, Mar 2026](https://thehackernews.com/2026/03/android-17-blocks-non-accessibility.html) (search summary; page unreachable); [Security Affairs](https://securityaffairs.com/?p=189497); [Malaysian Wireless](https://www.malaysianwireless.com/2026/03/android-17-beta2-advanced-protection-mode/)
- **Source caveat:** one low-quality source claimed an ECM firmware allowlist that cannot be overridden. Reputable outlets don't support that, so treat it as unreliable. — [search summary](https://blog-api.testapp.io/enable-unknown-sources-on-android-a-complete-how-to-guide/)

### Inferences
- **Effect on user flow for a sideloaded accessibility recorder on Android 13+:**
  1. Install.
  2. Try to enable accessibility; it is blocked as a "Restricted setting".
  3. App info, then ⋮ menu, then "Allow restricted settings".
  4. Enable the accessibility service.

  This is a major usability and trust barrier. A Shizuku-based recorder does not need accessibility at all, so it avoids this restriction. AAPM does not obviously affect it, although AAPM's other restrictions on USB/ADB were not verified.
- If an app falsely sets `isAccessibilityTool=true` it would conflict with Play policy. Outside Play, the effect under AAPM is unverified.

### Gaps
- I found no verified detail on Android 16 changes to restricted settings. I also could not confirm whether the AAPM accessibility restriction shipped unchanged in Android 17 stable, or whether AAPM also disables wireless debugging (which would break Shizuku).

## 7. AudioPlaybackCapture, Bluetooth/SCO, stereo split, codecs and processing

### Takeaway
The public `AudioPlaybackCapture` (MediaProjection) cannot capture call or VoIP downlink. Only `USAGE_MEDIA`, `USAGE_GAME` and `USAGE_UNKNOWN` are capturable, and only if the app allows it. Capturing `USAGE_VOICE_COMMUNICATION` needs `CAPTURE_VOICE_COMMUNICATION_OUTPUT`, which shell has. A 16 kHz mono PCM capture per side, encoded to Opus or AAC, is the practical standard. Stereo uplink/downlink separation is reliable only on some devices, mainly Pixel.

### Cited Findings
- **AudioPlaybackCapture rules:**
  - The playing app must use `USAGE_MEDIA`, `USAGE_GAME` or `USAGE_UNKNOWN`, and its policy must be `ALLOW_CAPTURE_BY_ALL`.
  - Apps targeting ≤ Android 9 are never capturable; Android 10+ targets default to allowing capture.
  - "The most restrictive capture policy is always applied."
  - The capturing app needs `RECORD_AUDIO`, and both apps must be in the same user profile.
  — [Capture video and audio playback](https://developer.android.com/media/platform/av-capture)
- **ShizuCallRecorder VoIP capture:** uses the hidden `AudioMixingRule`/`AudioPolicy` with `MIX_ROLE_PLAYERS` matching `USAGE_VOICE_COMMUNICATION`. This needs `CAPTURE_VOICE_COMMUNICATION_OUTPUT`; `USAGE_MEDIA` capture needs `CAPTURE_MEDIA_OUTPUT`. The Shell package holds both. — [ShizuCallRecorder `AudioPlaybackCapture.kt`](https://github.com/kitsumed/ShizuCallRecorder); [AOSP Shell manifest](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/packages/Shell/AndroidManifest.xml)
- **Stereo split:** ShizuCallRecorder captures each source as mono (`CHANNEL_IN_MONO`) and offers a stereo split of uplink and downlink. BCR warns that stereo separation is "only known to work on Pixel devices running newer versions of Android". — [ShizuCallRecorder `AudioConfig.kt`](https://github.com/kitsumed/ShizuCallRecorder); [BCR README](https://github.com/chenxiaolong/BCR)
- **BCR formats:**
  - OGG/Opus is the default on Android 10+, M4A/AAC the default on Android 9.
  - FLAC, WAV/PCM (least CPU) and AMR-WB/NB (mono only) are also offered.
  - Raw PCM s16le is encoded with the built-in MediaCodec encoders.
  - Sample metadata shows 16000 Hz.
  — [BCR README](https://github.com/chenxiaolong/BCR)
- **16 kHz cap:** ShizuCallRecorder fixes 16 kHz because high-priority system capture is capped at 16 kHz in AOSP policy config; 16 kHz equals HD voice (AMR-WB). It also has a `PcmVadDuckingProcessor` (VAD-based ducking/noise gating) at 20 ms blocks. — [ShizuCallRecorder source](https://github.com/kitsumed/ShizuCallRecorder)
- **Bluetooth:** ShizuCallRecorder claims recording works with Bluetooth or remote headsets, because it taps the telephony stream rather than the mic. — [ShizuCallRecorder README](https://github.com/kitsumed/ShizuCallRecorder)
- **Transport matters:** "Cellular/VoLTE traditionally uses a physical route… more straightforward to capture", whereas VoIP is "fully handled on the software side". — [ShizuCallRecorder troubleshooting](https://github.com/kitsumed/ShizuCallRecorder)

### Inferences
- **Codec choice:**
  - Telephony audio is band-limited (AMR-NB 8 kHz, AMR-WB/EVS 16 kHz, EVS-SWB up to 32 kHz on some VoLTE), so capturing above 16 kHz from VOICE_CALL brings little benefit.
  - Opus at 16 kHz mono, 24–32 kbps, gives transparent voice in small files.
  - AAC-LC/HE-AAC suits compatibility with players and iOS.
  - 48 kHz matters only for mic-based acoustic capture or VoIP playback capture (Opus-native VoIP).
- **Bluetooth/SCO with the accessibility mic method:**
  - When the call is routed to a BT headset, the phone's mic is inactive or not near the speaker, so mic-based recording gets neither side reliably.
  - The phone mic may pick up nothing, or the SCO mic is claimed by the call.
  - Telephony-stream methods (root/Shizuku) are unaffected.
  - This is inferred from routing behaviour, with no primary source.
- **NS/AGC/AEC:** `VOICE_COMMUNICATION` applies platform AEC/NS/AGC, which removes far-end leakage. For acoustic recording, use `VOICE_RECOGNITION`/`UNPROCESSED` (`AudioManager.getProperty(PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED)`) and apply software AGC after capture.

### Gaps
- I found no primary AOSP citation for the 16 kHz cap beyond ShizuCallRecorder's code comment, which points to Android 16 `audio_policy_configuration.xml` lines 76–79 and `Engine.cpp`.
- I found no official doc on SCO interactions with call-time capture.

## 8. VoIP app recording (WhatsApp etc.)

### Takeaway
VoIP apps play the remote voice with `USAGE_VOICE_COMMUNICATION` and capture with the private-by-default `VOICE_COMMUNICATION` source. Public AudioPlaybackCapture therefore cannot get the downlink, and a concurrent normal mic capture is silenced. Workarounds:
- an accessibility service (mic-only, acoustic far end);
- shell/Shizuku with `CAPTURE_VOICE_COMMUNICATION_OUTPUT` via a dynamic AudioPolicy (Android 14+, best-effort);
- root/system.

### Cited Findings
- **Silencing rules:**
  - `MODE_IN_COMMUNICATION` (VoIP) counts as an active call, so the same voice-call silencing rules apply.
  - `VOICE_COMMUNICATION` is privacy-sensitive and private by default from Android 11.
  - If one app is privacy-sensitive, "it receives audio and the other app gets silence even if it has a UI on top".
  — [Sharing audio input](https://developer.android.com/media/platform/sharing-audio-input)
- **Playback capture:** AudioPlaybackCapture only matches `USAGE_MEDIA`, `USAGE_GAME` and `USAGE_UNKNOWN`. — [Capture video and audio playback](https://developer.android.com/media/platform/av-capture)
- **ShizuCallRecorder VoIP support:**
  - Best-effort VoIP from Android 14+ via "Allow capture via the Playback API", which dynamically switches to a playback-capture plan when a VoIP/Wi-Fi call is detected.
  - Third-party app support is "not guaranteed".
  - "most third-party applications (like WhatsApp or Facebook) can only use VoIP… which will result in silent recordings" when that fails.
  — [ShizuCallRecorder README & troubleshooting](https://github.com/kitsumed/ShizuCallRecorder)
- **Cube ACR:** says its helper app is needed to record VoIP calls "only if your device allows it". — [Cube ACR Helper](https://cubeacr.app/helper.html) (search summary)

### Inferences
- With an accessibility service, a VoIP call's mic capture is not silenced, but the remote side again depends on speaker leakage. Speakerphone gives the most reliable result.
- **Why Android 14+ for the shell route:** ShizuCallRecorder gates VoIP to Android 14+. This suggests the hidden `AudioMixingRule.setTargetMixRole(MIX_ROLE_PLAYERS)` / loopback path with voice-communication usage only works from 14. That fits the `voiceCommunicationCaptureAllowed` flag comment in its code. Unverified against AOSP.

### Gaps
- I found no authoritative testing data on WhatsApp/Signal/Telegram recording success rates per method or device.
- I did not verify whether WhatsApp sets `ALLOW_CAPTURE_BY_NONE`/`SYSTEM`.
