# The fleet on a phone: the mobile lane

The contract page for the mobile lane of [plan-mobile.md](plan-mobile.md): the bridge folder, its records, the lists,
the flows, the settings and the verbs. Those sections arrive with the bridge's docs card (#554); this page starts with
the one section that waits on nobody, what IT is asked for (#571, the plan's slice V2).

## The IT ask

Nine asks, all of them standard Intune, Entra and Power Platform objects: no relay, no VM, no App Connector, no ZPA
segment, no custom connector and no Dataverse. The earlier report's relay needed twelve asks and a security review;
this lane replaces them (plan-mobile.md §Why this exists, *the path of least friction*). Each ask names the portal
path, the settings by the labels the portals print, the Microsoft Learn page it rests on, and why the fleet needs it.
IT decides every one of them; nothing here changes a policy.

**Licensing.** Microsoft Intune for the operator (the app protection policy, and *Available with or without
enrollment*); Microsoft Entra ID P1 for Conditional Access. No Power Apps premium on this path: every connector the app
and its flows use is a Standard connector under Microsoft 365 seeded rights. Premium becomes a question only if
Dataverse or a managed developer environment is ever used, and this lane uses neither.

**What a bystander sees.** The push on the lock screen is content-free by design: "an agent needs you", never a
repository, a ticket, a command or a payload. Intune's *Org data notifications* cannot redact a Power Apps push (ask 1),
so the fleet never puts anything in one that would need redacting. The words appear only inside the app, behind its
PIN.

### 1. App protection policy for Microsoft PowerApps (iOS/iPadOS, then Android)

- **Portal path.** Intune admin center > Apps > Protection > Create policy > iOS/iPadOS (then again for Android) >
  Apps > Select public apps > **Microsoft PowerApps**.
- **Settings.**
  - Data protection: *Send Org data to other apps* = **Policy managed apps**; *Restrict cut, copy, and paste between
    other apps* = **Policy managed apps with paste in**; *Encrypt Org data* = **Require**; *Restrict web content
    transfer with other apps* = **Microsoft Edge**; on Android *Screen capture and Google Assistant* = **Block**, on
    iOS *Screen capture* = **Block**.
  - *Org data notifications*: chosen knowingly, not by default. Power Apps mobile is not in the list of apps that
    honour it. On Android, **Block org data** on an app that does not support it means "notifications are blocked",
    so the phone gets no push at all; **Block** on an unsupported app means they are allowed. What #561 saw on an
    Android phone under *Block org data*: *not yet measured*. Until it is, the ask states the trade-off and leaves
    the value to IT: **Allow** on the Power Apps policy keeps the push, and the content-free push above is why that
    is safe; **Block org data** may silence every push on Android.
  - Access requirements: *PIN for access* = **Require**.
  - Conditional launch: *Jailbroken/rooted devices* = **Block access**; *Offline grace period* = **Wipe data**; *Min
    OS version* = the tenant's baseline.
- **Source.** [iOS app protection policy settings](https://learn.microsoft.com/intune/app-management/protection/ref-settings-ios);
  [Android app protection policy settings](https://learn.microsoft.com/intune/app-management/protection/ref-settings-android)
  (the *Org data notifications* row: "If not supported by the application, notifications are blocked");
  [Microsoft Intune protected apps](https://learn.microsoft.com/intune/app-management/ref-protected-apps) (Microsoft
  PowerApps: core settings, app configuration "No settings");
  [Data protection framework](https://learn.microsoft.com/intune/app-management/protection/data-protection-framework).
- **Why the fleet needs it.** The app shows approval summaries and what the agents said; the policy keeps them in a
  managed, PIN-locked, encrypted container and off screenshots.

### 2. App configuration for Power Apps on managed iOS devices

- **Portal path.** Intune admin center > Apps > Configuration > Create > Managed devices > iOS/iPadOS > targeted app
  **Power Apps** > Settings > *Use configuration designer*.
- **Settings.** Three String keys: `IntuneMAMUPN` set to Intune's user principal name token, `IntuneMAMOID` set to its
  user ID token, `IntuneMAMDeviceID` set to its device ID token, each in Intune's double-brace token syntax (the
  designer's own page spells them; this page does not, so nothing here reads as a literal value).
- **Source.** [Add app configuration policies for managed iOS/iPadOS devices](https://learn.microsoft.com/intune/app-management/configuration/configure-managed-ios);
  [How to create and assign app protection policies](https://learn.microsoft.com/intune/app-management/protection/create-policy)
  (§Device Management types; the 2409 release sends these three values automatically only to Excel, Outlook,
  PowerPoint, Teams and Word, not to Power Apps).
- **Why the fleet needs it.** On an enrolled iPhone, without `IntuneMAMUPN` the app is treated as unmanaged and the
  wrong policy, or none, reaches it.

### 3. Conditional Access for the phone

- **Portal path.** Microsoft Entra admin center > Entra ID > Conditional Access > Create new policy.
- **Settings.** Users: the operator (exclude the break-glass accounts). Target resources > Resources: **All resources
  (formerly 'All cloud apps')**, or the Power Platform audiences plus **Microsoft Flow Service**
  (`7df0a125-d3be-4c96-aa54-591f83ff541c`). Conditions > Device platforms: **iOS**, **Android**. Grant: **Require app
  protection policy** (and, for an enrolled phone, **Require device to be marked as compliant**) with **Require one of
  the selected controls**. *Enable policy*: **Report-only** first, then **On**. Not **Require approved client app**: its
  retirement moved from March to 30 June 2026, and since then policies that use it are read-only.
- **Source.** [Require approved client apps or app protection policy](https://learn.microsoft.com/entra/identity/conditional-access/policy-all-users-approved-app-or-app-protection);
  [Conditional Access: Grant](https://learn.microsoft.com/entra/identity/conditional-access/concept-conditional-access-grant);
  [Migrate approved client app to application protection policy](https://learn.microsoft.com/entra/identity/conditional-access/migrate-approved-client-app);
  [Configure identity and access management](https://learn.microsoft.com/power-platform/guidance/adoption/conditional-access)
  (Microsoft Flow Service is not in the **Office 365** target).
- **Why the fleet needs it.** The decision flow runs as the operator. If Microsoft Flow Service is left out while the
  apps are in, the app's call to the flow fails its token exchange and a tap on Approve does nothing.

### 4. The apps, published in Intune

- **Portal path.** Intune admin center > Apps > iOS/iPadOS (and Android) > Add.
- **Settings.** iOS store app **Power Apps** (App Store `id1047318566`, bundle `com.microsoft.msapps`); Managed Google
  Play **Power Apps** (`com.microsoft.msapps`); **Company Portal**; **Microsoft Authenticator**; **Microsoft Edge**.
  Assignment: **Required** for enrolled groups; **Available with or without enrollment** for a MAM-only phone.
- **Source.** [Add iOS store apps](https://learn.microsoft.com/intune/app-management/deployment/add-store-ios);
  [Add Android store apps](https://learn.microsoft.com/intune/app-management/deployment/add-store-android);
  [Assign apps to groups](https://learn.microsoft.com/intune/app-management/deployment/assign-groups);
  [Conditional Access: Grant](https://learn.microsoft.com/entra/identity/conditional-access/concept-conditional-access-grant)
  (the broker: Authenticator on iOS, Authenticator or Company Portal on Android).
- **Why the fleet needs it.** The policy protects only an app the phone has; the broker registers the device for
  Conditional Access; Edge is where the policy sends web links.

### 5. Environment and maker rights

- **Portal path.** Power Platform admin center > Manage > Environments; Power Apps > Apps > the app > Share.
- **Settings.** Which environment the app and its two flows live in (one user, confidential data: a named environment
  of the tenant's choosing, not a developer one); **Environment Maker** for the operator there; the app shared with the
  operator alone, permission **User**; sharing with *Everyone* off; the environment's sharing limits as IT sets them.
- **Source.** [Share a canvas app with your organization](https://learn.microsoft.com/power-apps/maker/canvas-apps/share-app);
  [Sharing limits in managed environments](https://learn.microsoft.com/power-platform/admin/managed-environment-sharing-limits);
  [Security roles and privileges](https://learn.microsoft.com/power-platform/admin/database-security) (Environment
  Maker).
- **Why the fleet needs it.** The operator imports the app and creates the flows; nobody else is meant to open it.

### 6. Data policy (DLP)

- **Portal path.** Power Platform admin center > Security > Data and privacy > Data policy (for the chosen
  environment, or the tenant policy that covers it).
- **Settings.** **Power Apps Notification** (v1 and v2), **SharePoint**, **OneDrive for Business**, **Microsoft 365
  Users** (the connector the plan calls Office 365 Users) and **Excel Online (Business)** in one group, **Business**.
  If an **advanced connector policy** (a strict allowlist) covers the environment, those connectors are on its
  allowlist, and no connector action control blocks the five actions the flows use.
- **Source.** [Connector classification](https://learn.microsoft.com/power-platform/admin/dlp-connector-classification)
  (all of these are in the list of connectors that can't be blocked by a classic data policy);
  [Advanced connector policies](https://learn.microsoft.com/power-platform/admin/advanced-connector-policies) (which
  can block them: a default-deny allowlist).
- **Why the fleet needs it.** A flow whose connectors sit in two groups is suspended; an allowlist without them stops
  the path without an error the phone can show.

### 7. Tenant isolation (a review item)

- **Portal path.** Power Platform admin center > Security > Identity and access > Tenant isolation.
- **Settings.** Confirm **Restrict cross-tenant connections** and its exceptions as they are. Nothing to change: the
  app, the flows, the lists and the OneDrive folder are all in the one tenant.
- **Source.** [Cross-tenant inbound and outbound restrictions](https://learn.microsoft.com/power-platform/admin/cross-tenant-restrictions).
- **Why the fleet needs it.** Only to have it on record that the path crosses no tenant boundary.

### 8. Zscaler (ZIA and ZCC)

- **Portal path.** ZIA admin portal > SSL inspection policy; ZCC app profile (and Intune, for a per-app VPN).
- **Settings.** SSL-inspection exemptions for Apple push, `*.push.apple.com` (Apple's `17.0.0.0/8`, TCP 5223, 443 and
  2197), and for Google push, `mtalk.google.com` and `fcm.googleapis.com` (TCP 5228–5230 and 443); the **Zscaler
  Recommended Exemptions** rule enabled; `*.wns.windows.com` bypassed for the laptop's OneDrive sync client; if the
  phone uses a per-app VPN on iOS, bound in the Power Apps assignment.
- **Source.** [Network endpoints for Microsoft Intune](https://learn.microsoft.com/intune/fundamentals/endpoints)
  (Apple and Firebase dependencies, which link to Apple's and Google's own port pages);
  [Configure the Jamf Cloud Connector](https://learn.microsoft.com/intune/device-security/conditional-access-integration/configure-jamf-cloud-connector)
  (the Apple `17.0.0.0/8` block over TCP 5223 and 443). The 2197 port and the FCM ports 5228–5230 are Apple's and
  Google's figures, taken from those linked pages: *unverified here*.
- **Why the fleet needs it.** An inspected push channel is a push that never arrives; the phone would learn about an
  approval only when the operator opened the app.

### 9. Teams, only if the Teams alert channel is ever used

- **Portal path.** Teams admin center > Teams apps > Manage apps; Intune admin center > Apps > Protection (the Teams
  policy).
- **Settings.** **Workflows** and **Approvals** allowed; the Teams app protection policy with *Org data notifications*
  = **Block org data**.
- **Source.** [Create flows in Microsoft Teams](https://learn.microsoft.com/power-automate/teams/teams-app-create);
  [Manage collaboration experiences in Teams for iOS and Android](https://learn.microsoft.com/intune/app-management/configuration/configure-teams-mobile).
- **Why the fleet needs it.** Not at all today: the push goes through Power Apps. This is the ask to make first if an
  alert ever goes through Teams instead.

### What Learn does not document

Marked as such, not asserted:

- **Power Apps mobile's Intune SDK version.** iOS *Screen capture* needs a minimum SDK; which one Power Apps ships is
  not on any Learn page: *unverified*.
- **The Conditional Access picker's display names** for the Power Platform audiences (the plan's list is by audience
  URL): *unverified*.
- **Zscaler's default exemption list.** help.zscaler.com did not render when the research was done, so whether the
  recommended exemptions already cover the push hosts is *unverified*.
