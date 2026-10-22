# Existing Android Call-Recording Apps and Their Techniques (Android 10–16, no root), status as of Oct 2026

> Research note: direct page fetches (WebFetch/curl) were blocked by the environment's network proxy, so all findings below come from web-search result summaries and snippets of the cited pages, not from full-page reads. The cited URLs are the pages those summaries were drawn from. Treat fine-grained details (exact menu paths, version numbers) as needing confirmation against the live pages.

## 1. Which apps/solutions are currently leading or working, and what technique each uses

### Takeaway
There are now three tiers. (1) OEM or Google system dialers that have privileged access to call audio: Google Phone (Pixel 6+ on Android 14+, plus non-Pixel phones on Android 9+, in a growing list of countries, always with a spoken announcement), Samsung's Phone app (region-gated by CSC; announced in the US since One UI 7), and Xiaomi, OnePlus, Honor and others, where availability is gated by region or SIM. (2) Play Store third-party apps (Cube ACR, ACR Phone, Truecaller and the generic "Call Recorder" apps). Since Google's May 2022 policy these can no longer use Accessibility for call recording from the Play build. They work only with an out-of-Play "helper" or connector APK, which uses Accessibility granted via "Allow restricted settings" or Shizuku/ADB shell privileges. (3) Open-source Shizuku recorders (ShizuCallRecorder) that use shell-UID privileges to open the VOICE_CALL audio source through a bundled scrcpy-server. Carrier/cloud "merge-call" recorders (TapeACall) bypass the OS entirely.

### Cited Findings

**Policy and platform background**
- Google announced on April 6, 2022 that third-party call-recording apps using the Accessibility API would be barred from Play, effective May 11, 2022. Google's stated position: "The Accessibility API is not designed and cannot be requested for remote call audio recording." — [Business Today](https://www.businesstoday.in/technology/news/story/googles-ban-on-call-recording-apps-to-come-into-effect-starting-today-333149-2022-05-11); [TheNextWeb](https://thenextweb.com/news/truecaller-call-recording-google-play-policy) (2022, older but foundational)
- Google said its own dialer and pre-installed OEM dialers could still record, depending on region and manufacturer, and that Google's dialer plays a clear "this call is now being recorded" alert to both sides — [TheNextWeb](https://thenextweb.com/news/truecaller-call-recording-google-play-policy) (2022)
- Android 9 Pie had already blocked the non-root workarounds then used by BoldBeast and ACR, whose developers confirmed that Google closed their method — [XDA, Android Pie blocks non-root call recording](https://www.xda-developers.com/android-pie-blocks-non-root-call-recording-apps/) (2018–19, older)
- NLL's compatibility table: on Android 10+ the Accessibility route does not give true two-way audio (it records mic/speaker), and the plain Play build records silence. The Shizuku-based helper is listed as giving real two-way recording on Android 10+ — [NLL Accessibility limitation page](https://nllapps.com/apps/cb/accessibility.htm); [NLL /no/ page](https://nllapps.com/no/)
- ACR Phone's Play listing itself states "Call recordings will be silent on Android 10+" (Play build without the helper) — [ACR Phone on Google Play](https://play.google.com/store/apps/details?id=com.nll.cb&hl=en_US&gl=US)

**Google Phone app (native, Pixel and non-Pixel)**
- Call recording started rolling out broadly to Pixel 6 and newer in November 2025 (tied to the November Pixel Feature Drop). It began expanding internationally in February 2026, with Google saying it would reach all supported markets by the end of February — [9to5Google, Feb 19 2026](https://9to5google.com/2026/02/19/pixel-call-recording-international/); [GSMArena, Nov 14 2025](https://www.gsmarena.com/newscomm-70296.php); [Android Central](https://www.androidcentral.com/google-phone-call-recording-rolling-out-pixels-globally)
- Requirements: Pixel 6+ on Android 14+. Non-Pixel phones need Android 9+ and the latest Phone app version. Heise reports Google confirmed non-Pixel support — [Heise](https://www.heise.de/en/news/Google-Phone-app-Update-brings-call-recording-and-Caller-Views-11203807.html); [Heise beta report](https://heise.de/-11174957); [Google Phone help](https://support.google.com/phoneapp/answer/9803950)
- Behavior: a short countdown, then a spoken message at the start tells all parties the call is being recorded, and another plays when recording stops. Google says this notice does not replace legal consent. There is an option to auto-record all calls from unknown numbers. Recordings stay local on the device (no cloud) — [Heise](https://www.heise.de/en/news/Google-Phone-app-Update-brings-call-recording-and-Caller-Views-11203807.html); [Malaysian Wireless, Feb 2026](https://www.malaysianwireless.com/2026/02/google-phone-app-call-recording/)
- Countries: Google publishes no full list ("widely available, but not in all countries"). It is not offered where call recording is illegal. One third-party guide lists Germany, Italy, Spain, Romania, France, Australia, Canada and Ireland as live in early 2026, with India in beta (unverified third-party list) — [Klear blog](https://klearphone.com/blog/does-google-phone-app-record-calls); [The Star, Feb 23 2026](https://www.thestar.com.my/tech/tech-news/2026/02/23/google039s-phone-app-on-android-will-soon-be-able-to-record-calls)
- Older history: Google Phone recording first came to non-Pixel devices (Nokia, Motorola Moto G7) in India around April–May 2020 — [9to5Google 2020](https://9to5google.com/2020/05/14/google-phone-call-recording-nokia-motorola-india/)

**Samsung native recorder**
- One UI 7 (beta Dec 2024 on the Galaxy S24) brought native recording to US Galaxy phones in the stock Phone app. The other party hears an announcement. At launch recording was manual per call, with no auto-record. It outputs an audio file plus an AI transcript — [Notebookcheck](https://www.notebookcheck.net/One-UI-7-finally-brings-native-call-recording-to-Galaxy-phones-in-the-US.930801.0.html); [Android Authority](https://www.androidauthority.com/samsung-call-recording-us-one-ui-7-3506960/); [9to5Google Dec 2024](https://9to5google.com/2024/12/10/samsung-galaxy-call-recording-one-ui-7-update/)
- One UI 8 (Android 16) path: Phone app > ⋮ > Settings > Record calls > Auto record calls, with the options All calls, Unsaved numbers or Specific numbers. Reported as not available during Wi-Fi calling — [Salestrail KB](https://www.salestrail.io/knowledge-base/sim/gsm-call-recording-on-samsung-devices-running-one-ui-8-android-16)
- Availability is tied to the CSC/software region, not physical location (for example, the DBT and BTU firmware regions, Germany and the UK, are restricted). Older country lists (Bangladesh, Egypt, India, Indonesia, Israel, Thailand, Ukraine, Vietnam, etc.) date from about 2022 and are flagged as possibly outdated — [Samsung Members](https://r2.community.samsung.com/t5/Galaxy-S/Samsung-Call-Recordings/td-p/11998846); [SamMobile](https://www.sammobile.com/news/call-recording-samsung-galaxy-smartphones-supported-countries/); [Samsung Magazine 2022](https://samsungmagazine.eu/en/2022/05/27/seznam-zemi-kde-samsung-umoznuje-nahravani-hovoru/)

**Xiaomi / HyperOS**
- Xiaomi's FAQ: on models using the Google Phone app, recording works only if model, region and SIM carrier all support it. Recordings appear under the Home tab of the Google Phone app — [Mi.com FAQ](https://www.mi.com/global/support/faq/details/KA-541461/)
- Third-party guide: the EEA ROM has recording removed (EU compliance) and the Global ROM is limited. China ROMs with the Mi Dialer support "Record calls automatically" — [Dr.Fone guide](https://drfone.wondershare.com/android-xiaomi/how-to-use-call-recording-on-xiaomi-with-hyperos-legal-guide.html); [cyrusyip 2023 guide](https://cyrusyip.org/en/posts/2023/11/27/miui-call-recording/) (2023, older)
- An XDA guide re-enables the native HyperOS (Mi Dialer) recorder on stock global ROMs without root. Results are mixed, and one user reports failure on an EU-region Xiaomi 15 — [XDA thread](https://xdaforums.com/t/enable-hyperos-native-call-recording-on-stock-global-rom-no-root-custom-rom-changing-rom-region-required.4750182/)

**OnePlus / Oppo / ColorOS / OxygenOS**
- OnePlus has largely shipped the Google Phone app (recording with an announcement) instead of its own recorder. XDA users report that on OxygenOS 15/16 the announcement and availability depend on the region setting or SIM country. Magisk modules (root) restore the OnePlus/ODialer recorder without the announcement — [Guiding Tech](https://www.guidingtech.com/how-to-record-calls-on-oneplus-phones/); [XDA OxygenOS 15/16 module](https://xdaforums.com/t/magisk-module-for-oneplus-dialer-messages-optional-and-enable-call-recorder-options-for-the-oxygenos-16-15-global-eu-in-and-na-root-required.4727965/page-11); [XDA OxygenOS 15 EU/NA](https://xdaforums.com/t/enable-oneplus-dialer-and-odialer-call-recorder-options-for-the-oxygenos-15-eu-and-na-root-required.4738929/)
- OnePlus community: the recording feature was enabled for more countries (date unclear) — [OnePlus Community](https://community.oneplus.com/threads/call-recording-feature-enabled-for-more-countries.1112698/)

**Motorola**
- Motorola uses Google's Phone app, and a Lenovo forum post says recording is "100% controlled by Google". No Motorola-specific recorder was found — [Lenovo forum](https://forums.lenovo.com/t5/moto-g40-fusion/Call-Recording-Storage-Path/m-p/5136691); [Android Authority Aug 2025](https://www.androidauthority.com/google-phone-call-recordings-3592542/)

**Honor**
- An active XDA thread ("Call Recording Android 12–16, new Honor") tracks Honor/MagicOS methods — [XDA Honor thread](https://xdaforums.com/t/call-recording-android-12-13-14-15-16-new-honor.4476703/page-39). A Romanian forum reports the SKVALEX build working through Shizuku on Honor MagicOS 9/10 and a OnePlus 15 — [Softpedia forum](https://forum.softpedia.com/topic/1253593-callrecorder-pentru-telefoanele-honor-cu-magicos-9-i-10/)

**Cube ACR (Cube Apps)**
- Technique: the Play-Store app plus a separately distributed **Cube ACR Helper** ("App Connector"), available from APKMirror, Galaxy Store and Amazon Appstore. The developer says the helper exists because Play policy forbids Accessibility for call recording. Steps: install Cube ACR from Play, install the Helper, grant permissions, then on Android 13+ go to App info > ⋮ > "Allow restricted settings", then enable "Use Cube ACR app connector". A third-party guide notes about a 4-second delay before recording starts — [Amazon Appstore listing](https://www.amazon.com/CUBE-APPS-LIMITED-Cube-Helper/dp/B0C5MG535V); [Galaxy Store](https://galaxystore.samsung.com/detail/com.catalinagroup.callrecorder.helper); [APKMirror helper](https://www.apkmirror.com/apk/cube-systems/cube-acr-helper/); [netnohow guide](https://netnohow.weebly.com/cubearc.html)
- Xataka tested it on Android 16 and found it works "better than expected", while flagging privacy concerns over the broad permissions — [Xataka Móvil](https://www.xatakamovil.com/movil-y-sociedad/empresas-llevan-anos-grabando-tus-llamadas-cube-acr-ha-encontrado-como-hacer-android)
- Cube's in-app intro pages warn that it "may not work correctly on your device" — [cubeacr.app intro](https://cubeacr.app/intro1b.html)
- Recommended troubleshooting settings: audio source "voice recognition (software)" and "force in-communication mode". Re-grant permissions and battery exemptions after OS updates. Bluetooth headsets can cause one-sided audio — [heilo.io guide](https://www.heilo.io/know-how/cube-acr-not-recording-alternatives)

**ACR Phone (NLL Apps)**
- ACR Phone is a full replacement dialer (default dialer/InCallService, SIP client, spam blocker). The Play build alone records silence on Android 10+ — [nllapps.com/android11](https://nllapps.com/android11); [Play listing](https://play.google.com/store/apps/details?id=com.nll.cb&hl=en_US&gl=US)
- **ACR Phone Helper (APH)** is distributed off-Play at acr.app or through NLL's own "ACR Store" (nll-store.apk). A community tutorial says the store is needed because Android 14 restricts Accessibility for sideloaded apps unless they were installed by a store using the session-installer API. APH has two modes: Accessibility, and a variant with built-in **Shizuku**, activated by ADB from a PC or by on-device Wireless Debugging (Developer Options required, no root). Shizuku must be re-activated after reboot — [acr.app](https://acr.app/); [Google Groups tutorial](https://groups.google.com/g/comp.mobile.android/c/7mCHCktUuKw) (2022–23 era)
- NLL claims two-way recording on Android 10+ through Shizuku, including over Bluetooth and wired headsets. Wi-Fi calling may still be one-sided on some phones due to OEM audio drivers — [acr.app](https://acr.app/)
- A root route also exists: the APH Magisk module — [XDA](https://xdaforums.com/t/module-aph-magisk-module-root-call-recorder-for-acr-phone.4488541/)

**Truecaller**
- Truecaller removed its Accessibility-based call recording in May 2022 because of the Play policy. It said devices with native recording are unaffected. No evidence was found of the Android feature returning — [TelecomTalk](https://telecomtalk.info/truecaller-discontinues-call-recording-feature-now-yes/512970/); [TheNextWeb](https://thenextweb.com/news/truecaller-call-recording-google-play-policy)

**BoldBeast**
- Historically used Accessibility plus device-specific audio tricks with a per-model compatibility list. A 2019 review says it worked on most devices according to the developer. Android Pie blocked its no-root method. No current Android 14–16 testing was found. BoldBeast also has a separate "VoIP Recorder" that lists WhatsApp, Skype, Viber, Messenger, Duo and Signal — [androidayuda](https://en.androidayuda.com/how-to-record-calls-on-your-android-without-having-the-phone-rooted/); [XDA Pie](https://www.xda-developers.com/android-pie-blocks-non-root-call-recording-apps/); [AppBrain VoIP Recorder](https://www.appbrain.com/app/voip-recorder-screen-recorde/com.boldbeast.voiprecorder)

**SKVALEX Call Recorder**
- Now works through Shizuku: permissions are granted to the app in Shizuku, which must be running. Reported working on Honor MagicOS 9/10 and a OnePlus 15 — [Softpedia forum](https://forum.softpedia.com/topic/1253593-callrecorder-pentru-telefoanele-honor-cu-magicos-9-i-10/)

**ShizuCallRecorder (open source, kitsumed) and forks**
- Mechanism: Shizuku launches a bundled **scrcpy-server** with shell (ADB) privileges. The server opens the VOICE_CALL audio source (normally not available to ordinary apps), and the app muxes the AAC stream into .m4a. Call state comes from phone-state/InCallService. The project is GPL-3.0 and available on F-Droid/IzzyOnDroid. Its table lists Android 14, 15 and 16 as supported, Android 11 as limited (crashes unless the screen is unlocked), and F-Droid lists Android 11+ — [GitHub kitsumed](https://github.com/kitsumed/ShizuCallRecorder); [F-Droid](https://f-droid.org/en/packages/com.kitsumed.shizucallrecorder); [hysenlabs](https://hysenlabs.com/en/projects/kitsumed-shizucallrecorder)
- Known issues: with the "voice call" source, some devices capture only the uplink and miss the downlink (issue #130). One Samsung user got mic-only audio, and Wi-Fi/VoWiFi calls capture only the user side (issue #13). The maintainer plans a v2.0.0 audio rework — [Issue #130](https://github.com/kitsumed/ShizuCallRecorder/issues/130); [Issue #13](https://github.com/kitsumed/ShizuCallRecorder/issues/13)
- Forks: yishaik/ShizuCallRecorder targets the Pixel 9 Pro (its README says it has not been call-tested). Ever-Call-Recorder is another Shizuku two-side recorder — [yishaik fork](https://github.com/yishaik/ShizuCallRecorder); [Ever-Call-Recorder](https://github.com/hari161008/Ever-Call-Recorder)

**TapeACall (and similar "Rev Call Recorder"-style services)**
- Technique: a three-way/conference call that merges your call with the service's recording line, so recording happens server-side. It needs carrier 3-way calling (not offered by some US MVNOs such as SimpleTalk and H2O) and uses plan minutes. The newer listing claims automatic outgoing recording with "no more call merging" for iOS — [TapeACall App Store](https://apps.apple.com/app/id573751328); [NASW review](https://www.nasw.org/article/smartphone-basics-record-call-and-transcribe-it-later) (about 2019); [SoftwareSuggest](https://www.softwaresuggest.com/tapeacall/mobile-app)

**Generic Play "Call Recorder – Automatic" apps (Smartmobitools and similar)**
- These offer an audio-source selector (voice call, communication, camcorder, etc.). On Android 10+ they typically capture only the mic side unless the device allows otherwise. A "Call Recorder Automatic" listing (Aug 2025) tells users the app will be removed from Play and to install from the developer's own store — [Softpedia review](https://mobile.softpedia.com/android/Automatic-Call-Recorder-Android-Review-2632.html); [Cafebazaar listing](https://cafebazaar.ir/app/com.automaticcallrecorder.autorecordphonecalls?l=en)
- Talker ACR also uses an off-Play "Talker ACR Helper" with the "Allow restricted settings" flow — [Talker ACR install guide](https://talkeracr.app/installation-guide.html)

**Otter / Google Recorder**
- Neither captures cellular call audio directly. Otter pauses live recording during a phone call. The workaround is speakerphone plus the mic, with degraded accuracy — [withallo guide](https://withallo.com/blog/how-to-record-phone-calls-with-otter-ai); [Android Authority Recorder wishlist](https://androidauthority.com/google-pixel-recorder-features-wishlist-3209137)

### Inferences
- The dominant no-root technique in 2025–26 is **Shizuku/ADB shell privileges**, used by ACR Phone APH, SKVALEX, ShizuCallRecorder and Ever. These give real two-way audio through VOICE_CALL/CAPTURE_AUDIO_OUTPUT-class access, at the cost of re-activation after every reboot (wireless debugging). Accessibility plus an off-Play helper (Cube ACR, Talker) is the second technique. Its quality varies: it is often one-sided or near-both-sides depending on OEM audio routing with the VOICE_RECOGNITION/VOICE_COMMUNICATION sources.
- The onboarding burden is high for all third-party approaches: sideload, "Allow restricted settings", Accessibility toggle, battery-optimization exemption, and for Shizuku also Developer Options, Wireless Debugging, pairing and re-pairing after reboot.
- Native dialers (Google, Samsung) are now the most reliable path for mainstream users, but they come with mandatory announcements (Google always, Samsung US) and region gating.
- Google's developer-verification requirement for sideloaded apps begins **Sept 30, 2026** in Brazil, Indonesia, Singapore and Thailand, with global expansion on certified devices in 2027. Helper APKs from unregistered developers would then require ADB or the new "advanced flow" — [Help Net Security, Jun 2026](https://www.helpnetsecurity.com/2026/06/19/android-developer-verification-rollout-markets/); [Android Authority](https://www.androidauthority.com/android-sideloading-changes-timeline-3679204/); [Malaysian Wireless](https://www.malaysianwireless.com/2026/06/google-android-developer-verification-sept-30/). This is a likely risk for helper-APK distribution models (inference; no source discusses call recorders specifically).

### Gaps
- No full-page reads were possible, so exact current version numbers and the dates of the Cube/NLL help pages could not be verified.
- No official, current country list exists for Google Phone recording or for Samsung One UI 8.
- Whether Samsung US One UI 8 added auto-record without an announcement is unconfirmed.
- I could not confirm the Smartmobitools developer identity or a current Play listing. No Android-specific source for "Rev Call Recorder" turned up (Rev's recorder is historically iOS and conference-based).
- No evidence was found on whether Google Phone recording on non-Pixel phones is broadly enabled on Samsung/Xiaomi devices that ship Google Dialer, beyond Xiaomi's FAQ.

## 2. Which apps record VoIP calls (WhatsApp, Telegram, Signal, Zoom) and how

### Takeaway
No VoIP app offers built-in recording, and native dialer recorders only cover cellular (and Samsung's is even disabled during Wi-Fi calling). Third-party options are Cube ACR (VoIP support claimed: WhatsApp, Telegram, Viber and others, with the Helper/connector required), ACR Phone (VoIP only with APH, otherwise silent), BoldBeast VoIP Recorder and Talker ACR. All rely on the same Accessibility/connector or Shizuku techniques and are device-dependent. The fallback is the system screen recorder with internal audio or "media + mic", or the speakerphone.

### Cited Findings
- NLL: ACR Phone can record VoIP apps such as WhatsApp, but APH is needed, otherwise recordings are silent — [NLL VoIP page](https://nllapps.com/apps/cb/voip-call-recording.htm)
- Cube ACR's listing claims VoIP recording (WhatsApp, Telegram, Viber, etc.) but warns that not all devices support VoIP recording and users should test on their own device — [APKMirror Cube ACR](https://www.apkmirror.com/?p=1126334); [vibe.us WhatsApp guide](https://vibe.us/blog/how-to-record-a-whatsapp-call/)
- BoldBeast VoIP Recorder claims WhatsApp, Skype, Viber, Messenger, Duo and Signal — [AppBrain](https://www.appbrain.com/app/voip-recorder-screen-recorde/com.boldbeast.voiprecorder)
- Talker ACR's listing: "not all Android devices support the recording of VoIP calls" — [Google Play Talker ACR](https://play.google.com/store/apps/details?id=com.talker.acr&hl=en_US)
- WhatsApp has no built-in recorder. The Android 10+ built-in screen recorders on Samsung, Pixel, Xiaomi and OnePlus can capture internal audio or "media + mic", which is the most reliable way to get both sides, but the OEM may restrict VoIP capture — [vibe.us](https://vibe.us/blog/how-to-record-a-whatsapp-call/); [meetgeek](https://meetgeek.ai/blog/how-to-record-whatsapp-calls)
- ShizuCallRecorder user report: WhatsApp worked using a VOICE_COMMUNICATION mic plus downlink configuration — [Issue #13](https://github.com/kitsumed/ShizuCallRecorder/issues/13)
- Samsung native auto-record is not available during Wi-Fi calling — [Salestrail KB](https://www.salestrail.io/knowledge-base/sim/gsm-call-recording-on-samsung-devices-running-one-ui-8-android-16)

### Inferences
- VoIP apps play the far side through the normal media/voice-communication stream. The AudioPlaybackCapture API (Android 10+) is opt-out for voice-communication usage, so a Shizuku/shell-privileged or Accessibility-assisted recorder plus VOICE_COMMUNICATION mic is the practical approach. That would explain why results vary by app and OEM. (This is an inference based on the issue reports; the API details are not sourced here.)

### Gaps
- No independent tests for Signal, Telegram or Zoom recording with Cube/ACR on Android 15/16 were found.

## 3. Recent user reports (XDA, Reddit, forums) on Samsung One UI 6/7/8, Pixel Android 15/16, Xiaomi HyperOS 2/3

### Takeaway
User reports are mixed. Cube ACR with Helper works for many users after enabling restricted settings, but there are several One UI 8 / Android 16 Samsung reports of only one's own voice being recorded, and a Polish forum suspects an extra One UI 8 restriction. Android 15 upgrades broke recording for some users. The Shizuku-based tools are what XDA users recommend for true two-way audio. On Xiaomi, region (EEA vs Global vs China) determines native recording.

### Cited Findings
- XDA (Android 15): the Cube helper toggle was greyed out until "Allow restricted settings" was chosen from the top-right menu, after which recording worked. An S22 Ultra user on Android 16 with Cube and Helper reports only their own voice is recorded, and support did not respond — [XDA "Cube ACR in Android 15"](https://xdaforums.com/t/cube-acr-in-android-15.4733373/)
- Polish forum (Galaxy A55, One UI 8 / Android 16): recording still failed after the helper setup, and a commenter suspects One UI 8 added a restriction — [MIUIPolska forum](https://miuipolska.pl/forum/topic/66224-nagrywanie-rozm%C3%B3w-z-cube-acr-nie-dzia%C5%82a/)
- A forum claim says many users had recording problems after upgrading to Android 15, attributed to audio-source restrictions (unverified) — [justuseapp forum](https://forums.justuseapp.com/en/post/TTJTQDITYI/records-only-my-voice-helper-is-installed)
- Samsung Members threads on One UI 8 recording and auto-record behavior — [Samsung Members Auto Call Recording](https://r2.community.samsung.com/t5/Galaxy-S/Auto-Call-Recording/td-p/21462274)
- XDA "Best option for non-root call recording?" thread: an older Accessibility-based ACR "doesn't work since Google forbid devs to use accessibility services" (about mid-2025) — [XDA](https://xdaforums.com/t/best-option-for-non-root-call-recording.4639309/)
- Xiaomi: an XDA no-root method to enable the HyperOS native recorder on global ROMs had mixed results and failed on an EU Xiaomi 15 — [XDA HyperOS](https://xdaforums.com/t/enable-hyperos-native-call-recording-on-stock-global-rom-no-root-custom-rom-changing-rom-region-required.4750182/)
- OnePlus OxygenOS 15/16: announcement and availability depend on region or SIM, per XDA — [XDA](https://xdaforums.com/t/magisk-module-for-oneplus-dialer-messages-optional-and-enable-call-recorder-options-for-the-oxygenos-16-15-global-eu-in-and-na-root-required.4727965/page-11)

### Inferences
- For Pixel on Android 15/16, the realistic no-root third-party options are Shizuku-based tools (ACR Phone + APH Shizuku, ShizuCallRecorder) or Google Phone's native recorder with an announcement where the region allows. No Pixel-specific Cube test result was found.

### Gaps
- No Reddit threads were retrieved (search did not surface them). Pixel Android 16 user reports specific to Cube ACR or APH were not found. No HyperOS 3-specific reports were found.
