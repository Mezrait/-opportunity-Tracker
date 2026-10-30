# Part B – Getting Started with Keycloak Identity Provider

Keycloak is an open-source identity and access management (IAM) server. Instead of every application storing its own users and passwords, the applications send the user to Keycloak to log in, and Keycloak gives the application a signed token that says who the user is and what they are allowed to do. It supports the standard protocols OpenID Connect, OAuth 2.0 and SAML [5]. In this part I ran Keycloak in Docker, secured the admin account with a one-time password, created my own realm, user and clients, and looked at the tokens that Keycloak issues.

## Step 1 – Running Keycloak in Docker

Docker Desktop was already installed on my Windows laptop, but at first the docker command did not work inside Ubuntu. I had to turn on the WSL integration for my Ubuntu distribution in the Docker Desktop settings. After that I started Keycloak as root with:

    docker run --name keycloak -p 8080:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=Mezrait -e KC_BOOTSTRAP_ADMIN_PASSWORD=1093911 quay.io/keycloak/keycloak:latest start-dev

- --name keycloak gives the container a fixed name, so I can stop and start the same container later without losing my configuration.
- -p 8080:8080 publishes port 8080 of the container on port 8080 of my machine, so the browser can open http://localhost:8080.
- The two -e variables create the first admin account: my first name as the username and my student ID as the password.
- start-dev runs Keycloak in development mode.

The image was not on my machine yet, so Docker downloaded it first. In the log I could see three useful things: the version is Keycloak 26.8.1, the server warns "Running the server in development mode. DO NOT use this configuration in production", and it says "Created temporary admin user with username Mezrait".

[IMG b61.png] Figure 29: Downloading the image and starting Keycloak 26.8.1 in development mode

In a second terminal I checked the running container with docker ps. It shows the container name keycloak, the image quay.io/keycloak/keycloak:latest, the status "Up" and the port mapping 0.0.0.0:8080->8080/tcp.

[IMG b62.png] Figure 30: docker ps shows the Keycloak container running with port 8080 published

Development mode is fine for a lab, but it is not secure for real use: it uses plain HTTP instead of HTTPS, relaxed settings, and a local H2 database inside the container (jdbc-h2 is in the list of installed features in Figure 29). If the container is deleted, everything I configure is lost. In production Keycloak should run with start, HTTPS, a real hostname and an external database.

## Step 2 – Logging in to the Admin Console

I opened http://localhost:8080 in the browser and logged in with the bootstrap admin account. I showed the password on the login page so the screenshot includes my student ID.

[IMG b66c.png] Figure 31: Keycloak admin login with the bootstrap account

After logging in, the admin console opened in the master realm.

[IMG b64.png] Figure 32: The Keycloak admin console after logging in

Two things I noticed:

- I typed the username Mezrait, but the console shows mezrait. Keycloak stores usernames in lower case, so usernames are not case-sensitive.
- A yellow banner says "You are logged in as a temporary admin user. To harden security, create a permanent admin account and delete the temporary one." In Keycloak 26 the bootstrap admin is meant only for the first setup. This makes sense, because the bootstrap password was passed on the command line, where it can end up in the shell history and in docker inspect.

## Step 3 – Two-factor authentication (OTP) for the admin

A password alone is one factor (something you know). To make the admin account stronger I added a one-time password from my phone (something you have). In Users → mezrait → Details I added Configure OTP to the Required user actions. A required action is something Keycloak forces the user to complete at the next login.

[IMG b65.png] Figure 33: Adding the required action Configure OTP to the admin user

Then I signed out and logged in again with my username and password. This time Keycloak did not open the console. It showed the Mobile Authenticator Setup page with a QR code and a list of supported apps (Google Authenticator, FreeOTP, Microsoft Authenticator). I scanned the QR code with the authenticator app on my phone and entered the 6-digit code that the app generated.

[IMG b67.png] Figure 34: Setting up the authenticator app with the QR code

After submitting the code I was logged in to the console again.

[IMG b68.png] Figure 35: Logged in to the admin console after the OTP setup

To check that OTP is really enforced, I signed out and logged in once more. After the password Keycloak now asks for the one-time code. Two OTP devices are listed on this page, "unnamed" and "mezrait", so two authenticator registrations exist for this account. The "unnamed" one is the registration from Figure 34, where I left the Device Name field empty.

[IMG b69.png] Figure 36: The next login asks for a one-time code

The Credentials tab of the admin user also shows the two credential types, Password and OTP.

[IMG b70.png] Figure 37: The admin user now has a password and an OTP credential

How it works: the QR code contains a shared secret key. My phone and Keycloak both combine this secret with the current time to calculate the same 6-digit code, which changes every 30 seconds (TOTP, time-based one-time password [6]). Because the code depends on the secret on my phone, a stolen password alone is not enough to log in.

My reflections:

- The QR code is the secret itself. Anyone who has a copy of the QR code (for example from a screenshot) can generate the same codes. In my lab it is acceptable because this Keycloak is temporary and runs only on my laptop, but in a real system the QR code should never be shared or saved.
- Every registered OTP device is another way to pass the second factor. An unused registration (like the extra "unnamed" one) should be removed, so that only devices the user actually controls are accepted.
- OTP protects against stolen passwords, but not against phishing in real time: if a fake site asks for the password and the code and forwards them immediately, the attacker can still log in. Phishing-resistant methods like WebAuthn/passkeys (which Keycloak also offers in the required actions list in Figure 33) are stronger.

## Step 4 – Creating a new realm

A realm is a separate space with its own users, roles, clients and settings. Users of one realm cannot log in to another realm. The master realm is used to administer Keycloak itself, so applications and their users should be put in their own realm. Then a problem in an application realm does not give access to Keycloak's administration.

I created the realm MyApp911 (911 are the last three digits of my student ID) from Manage realms → Create realm.

[IMG b71.png] Figure 38: The new realm MyApp911 next to the master realm

## Step 5 – Creating a user and testing the login

Inside MyApp911 I created a user with my family name as the username: menber. The lab sheet says once to use the family name and once that the screenshot should show the first name as the username, which is contradictory; I followed the step itself and used the family name. I also filled in an email, first name and last name. Keycloak 26 requires these fields for the user profile, and without them the user would be asked to fill them in at the first login. I checked that the top left of the console showed MyApp911 as the current realm, so that the user would not be created in master by mistake.

[IMG b73.png] Figure 39: Creating the user menber in the MyApp911 realm

[IMG b74.png] Figure 40: The user menber was created

Then I set the password in the Credentials tab. The Temporary switch is On by default. If it stays On, the user must choose a new password at the first login. Since the lab asks for my student ID as the password, I switched Temporary Off.

[IMG b76.png] Figure 41: Setting the password with Temporary switched off

[IMG b77.png] Figure 42: The password was set successfully

To test the user, I opened the account page of the realm, http://localhost:8080/realms/MyApp911/account, in an incognito window, so that the admin session would not interfere. The login page shows the realm name MYAPP911, which confirms that the user logs in to my realm and not to master.

[IMG b78.png] Figure 43: Logging in as menber to the MyApp911 account console

The login went directly to the account console, without asking for a new password, so the Temporary setting worked.

[IMG b79.png] Figure 44: The account console of the user menber

Finally I updated the account information as the lab asks. I changed the first name to Mezrait1093911 and saved, and Keycloak confirmed "Your account has been updated". This shows that users can manage their own profile in Keycloak without the admin.

[IMG b80.png] Figure 45: Updating the account information as the user

## Step 6 – Creating a public client

A client is an application that uses Keycloak for login. A public client is an application that runs where users can see its code, like a single-page app in the browser or a mobile app. It cannot keep a secret, so it does not get a client secret.

In MyApp911 I created the client my-client911 with the OpenID Connect protocol.

[IMG b81.png] Figure 46: Creating the client my-client911

[IMG b82.png] Figure 47: The client was created

In the Access settings I added the valid redirect URI https://www.keycloak.org/app/* and the web origin https://www.keycloak.org. The redirect URI is a security check: after login, Keycloak will only send the user (and the authorization code) back to an address on this list. Without it an attacker could make Keycloak send the code to their own site. The web origin allows the JavaScript on keycloak.org to call the Keycloak token endpoint (CORS).

[IMG b83.png] Figure 48: Valid redirect URI and web origin of my-client911

In the Capability config, Client authentication is Off, which makes it a public client. Standard flow (the authorization code flow, where the user logs in on the Keycloak page) and Direct access grants are enabled.

[IMG b85.png] Figure 49: Capability config of the public client

Two security notes:

- Keycloak shows a warning next to Require PKCE, which is Off. For a public client PKCE is important: since there is no secret, PKCE is what stops an attacker who steals the authorization code from exchanging it for a token [7].
- Direct access grants lets an application send the user's username and password directly to the token endpoint. The lab asks to enable it, but in my opinion it is not a good idea for a public client, because the application then sees the user's password, which is exactly what an identity provider is supposed to avoid. The current OAuth 2.0 security best practice says this grant must not be used [8].

## Step 7 – Testing the public client with the Keycloak demo application

I opened the demo application https://www.keycloak.org/app/ in a new incognito window and entered the Keycloak URL http://localhost:8080, the realm MyApp911 and the client my-client911. The settings are kept in the page address.

[IMG b87.png] Figure 50: The demo application configured for my realm and client

Before clicking Sign in I opened the developer tools (F12) on the Network tab with logging kept between pages, so that the token request would be recorded. After Sign in, the browser was redirected to the MYAPP911 login page, I logged in as menber, and the demo app showed "Hello, Mezrait1093911 Menber". The name comes from the token, and it is the first name I changed in Step 5.

[IMG b88.png] Figure 51: Logged in to the demo application as menber, with the network requests

The network list shows the authorization code flow:

1. auth?client_id=my-client911&redirect_uri=… with status 302: the browser was sent to Keycloak's authorization endpoint, I logged in there, and Keycloak redirected back to the demo app with a one-time authorization code in the address.
2. token (type fetch): the JavaScript of the demo app sent the code to Keycloak's token endpoint and received the tokens.

The Response tab of the token request shows what Keycloak returned:

[IMG b89.png] Figure 52: The token response in the developer tools

- access_token – a JWT that the application sends to APIs to prove who the user is. It expires after 300 seconds (expires_in).
- refresh_token – used to get a new access token without logging in again; it is valid for 1800 seconds (refresh_expires_in).
- id_token – a JWT with information about the login and the user, for the application itself (OpenID Connect).
- token_type Bearer – whoever holds the token can use it, so tokens must be protected like passwords.
- scope "openid profile email" – the information the application is allowed to receive.

The short lifetime of the access token limits the damage if a token is stolen.

The Payload tab shows what the demo app sent to get these tokens:

[IMG b90.png] Figure 53: The token request sent by the demo application

It sent grant_type=authorization_code, the code, the client_id and redirect_uri, and also a code_verifier. The code_verifier means the demo app uses PKCE: when the login started, it sent a hash of a random value (the code challenge), and now it proves it is the same application by sending the original value [7]. So in this case the app protects itself with PKCE even though my client does not require it. A malicious or badly written app would not, which is why Require PKCE should be On for public clients.

## Step 8 – Creating a confidential client

A confidential client is an application that runs on a server, where users cannot see its code, so it can keep a secret. It proves its identity to Keycloak with a client secret. With the client credentials grant it can also get a token for itself, without any user being involved, for example a backend service that calls another API.

I created the client my-Confidential-Client911 in the MyApp911 realm.

[IMG b91.png] Figure 54: Creating the confidential client my-Confidential-Client911

In the Capability config I turned Client authentication On (this is what makes the client confidential) and enabled Service account roles and Direct access grants. My first save did not have Service account roles ticked. I noticed this because the client had no "Service account roles" tab, and without it Keycloak refuses the client credentials grant. After I ticked it and saved again, Keycloak showed "Client successfully updated".

[IMG b99.png] Figure 55: Capability config of the confidential client with Client authentication and Service account roles enabled

Because Client authentication is On, the client now has a Credentials tab with the client secret. Keycloak generates it automatically. I made it visible to copy it into the terminal.

[IMG b98.png] Figure 56: The client secret in the Credentials tab

The client secret is effectively the password of the application. Anyone who has it can get tokens as this client, so in a real system it must be stored safely (for example in a secrets manager or an environment variable, never in source code) and replaced with Regenerate if it leaks. I am showing it here only because this Keycloak is a temporary local lab instance.

## Step 9 – Requesting a token with curl

I saved the secret in a shell variable, so I did not have to paste it into every command:

[IMG b100.png] Figure 57: Storing the client secret in a variable

First I ran the curl command exactly as it is printed in the lab sheet. In the sheet there is a space after client_secret= ('client_secret= my-Confidential-ClientXYZ-secret'). Keycloak rejected it with "unauthorized_client" / "Invalid client or Invalid client credentials", because the space becomes part of the secret, so the secret no longer matches. Then I ran the same command without the space and Keycloak returned an access token.

    curl -s -L -X POST 'http://localhost:8080/realms/MyApp911/protocol/openid-connect/token' \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode 'client_id=my-Confidential-Client911' \
      --data-urlencode "client_secret=$SECRET" \
      --data-urlencode 'grant_type=client_credentials'

[IMG b102.png] Figure 58: The lab's command fails because of the space; the corrected command returns a token

The response is different from the one in Step 7:

- There is an access_token with expires_in 300 (5 minutes) and token_type Bearer.
- There is no refresh_token and no id_token (refresh_expires_in is 0). In the client credentials grant there is no user and no login session, so there is nothing to refresh and no user identity to describe. When the token expires, the service simply asks for a new one with its secret.
- The scope is "profile email" without openid, again because no user logged in.

### Inspecting the JWT

A JWT has three parts separated by dots: header.payload.signature. The header and payload are only Base64URL-encoded, not encrypted, so anyone who has the token can read them. I decoded them in the terminal with a short Python command, so the token did not have to leave my machine:

[IMG b103.png] Figure 59: The header and payload of the access token, decoded in the terminal

I also pasted the token into the online decoder at jwt.io, as the lab asks. It shows the same header and payload.

[IMG b101.png] Figure 60: The same token decoded on jwt.io

The important fields are:

| Claim | Value | Meaning |
|---|---|---|
| alg | RS256 | signed with RSA and SHA-256 using the realm's private key |
| kid | gE_H1A5OpA… | which realm key signed the token |
| iss | http://localhost:8080/realms/MyApp911 | the realm that issued the token |
| iat / exp | 1793336180 / 1793336480 | issued 30 Oct 2026 08:56:20, expires 09:01:20 (+04:00), so it is valid for 300 seconds |
| azp / client_id | my-Confidential-Client911 | the client that requested the token |
| sub | a59687e6-29bf-4029-ba0d-b1cc38b73fe9 | the internal ID of the account the token belongs to (here the service account) |
| preferred_username | service-account-my-confidential-client911 | the readable name of that account: the token belongs to the client's service account, not to a person |
| aud | account | the audience: this token is meant for Keycloak's built-in account client |
| realm_access / resource_access | default-roles-myapp911, offline_access, uma_authorization; account roles | the roles of the service account |
| clientAddress | 172.17.0.1 | the request came through the Docker network gateway, because Keycloak runs inside a container |

How the token is validated: an API that receives this token does not need to ask Keycloak each time. It downloads the realm's public keys once from Keycloak's JWKS endpoint, finds the key with the same kid, and checks the RS256 signature. If even one character of the payload is changed, the signature check fails. After that it checks that iss is the expected realm, that exp is in the future and that aud matches the API. For this particular token aud is account, so it is only meant for Keycloak's account client; any other API should reject it unless it is configured to accept that audience. To use it for my own API, I would add an audience mapper to the client so the API's name appears in aud. Because the token is only signed and not encrypted, it must not contain secrets, and it must be sent only over HTTPS.

My reflection on jwt.io: pasting a real token into a website is risky, because a bearer token can be used by whoever has it until it expires. jwt.io says it decodes in the browser, but for real tokens decoding them locally, like I did in Figure 59, is safer. In this lab the risk is small because the token expired five minutes later and the server only runs on my laptop.

## Step 10 – Login with Google (identity brokering)

In this step Keycloak does not check the password itself. It acts as a broker: it sends the user to Google, Google authenticates them and sends Keycloak an OpenID Connect token, and Keycloak then logs the user in to my realm. For this, Keycloak becomes a client of Google, in the same way that my demo app was a client of Keycloak in Step 7. I used my existing realm MyApp911 instead of creating another realm, because it already has a working account console to test with.

### Google Cloud side

First I opened Identity providers → Google in Keycloak. Keycloak shows the Redirect URI it expects Google to send the user back to: http://localhost:8080/realms/MyApp911/broker/google/endpoint.

In the Google Cloud Console I created a new project for the lab.

[IMG b106.png] Figure 61: Creating the Google Cloud project ITE408-Lab3-1093911

Then I configured the Google Auth Platform (the OAuth consent screen) with an app name, my contact email and the audience External. While an app is in "Testing" status, only listed test users can log in, so I added my own Gmail address as a test user.

[IMG b110.png] Figure 62: External audience in Testing mode with my Gmail as the only test user

Then I created an OAuth client of type Web application and added the Keycloak redirect URI under Authorized redirect URIs. Google only sends the authorization code back to addresses on this list, which is the same protection as the valid redirect URIs in my own Keycloak client (Step 6). Google accepts plain http here only because the host is localhost; a real server would need https.

[IMG b111.png] Figure 63: The Google OAuth client with the Keycloak redirect URI

Google then showed the client ID and the client secret. It warns that the secret cannot be viewed again after closing the dialog. I have hidden the secret in the screenshot.

[IMG b112_redacted.png] Figure 64: Google created the OAuth client (client secret hidden)

### Keycloak side

Back in Keycloak I entered Google's client ID and client secret in the Google identity provider and set the display name to Google (secret hidden in the screenshot). One thing I had to be careful about: Chrome had automatically filled these two fields with my saved Keycloak admin username and password, so I had to delete them and paste the Google values.

[IMG b113_redacted.png] Figure 65: Configuring the Google identity provider in the MyApp911 realm

[IMG b114.png] Figure 66: Google is now an identity provider of the realm

### Testing the login

I opened the account console of MyApp911 in an incognito window. The login page now has a "Sign in with Google" button under the normal username and password form.

[IMG b115.png] Figure 67: The MyApp911 login page with the Sign in with Google button

I clicked it, chose my Gmail account on Google's page, and was sent back to Keycloak and logged in to the account console. The username is my Gmail address, and the first name, last name and email were copied from my Google profile.

[IMG b116.png] Figure 68: Logged in to the MyApp911 account console with my Google account

In the admin console the realm now has two users: menber, which I created by hand, and mezraitmenber@gmail.com, which Keycloak created automatically the first time I logged in with Google (created at 9:21:51 AM).

[IMG b117.png] Figure 69: The Google user appears in the realm's user list

[IMG b118.png] Figure 70: The user created through Google login

Observations:

- This user has no password in Keycloak. Authentication is fully delegated to Google, so Google's security (including my Google 2-step verification, if enabled) protects this login, and my Keycloak never sees my Google password.
- Email verified is Off for both users and the user list shows a warning icon next to the emails. For the Google user this is because the identity provider is not configured to trust the email from Google. Google does verify Gmail addresses, so in practice I could turn on "Trust Email" for this provider, but I left the default because trusting an external provider's data is a decision an administrator should make on purpose.
- Anyone with a Google account could create a user in my realm this way, unless I restrict it (for example with Google's Hosted Domain setting for an organization, or by changing the first broker login flow so new users are not created automatically). In my case Google's Testing mode already limits it to my test user.

## Part B summary

| Concept | What I did / saw |
|---|---|
| Realm | MyApp911, separate from the master realm used to administer Keycloak |
| User | menber, password not temporary, can update their own profile |
| 2FA | TOTP from an authenticator app enforced for the admin account |
| Public client | my-client911, no secret, authorization code flow (the demo app used PKCE) |
| Confidential client | my-Confidential-Client911, client secret, client credentials grant, service account |
| Token | RS256-signed JWT, valid 5 minutes, contains issuer, client, subject and roles |
| Identity brokering | Login with Google; Keycloak created the user automatically from the Google profile |

Part B showed me how an identity provider moves authentication out of the applications: the demo app never saw menber's password, it only received a signed token from Keycloak. I also found that many security properties depend on settings that are easy to get wrong: Temporary passwords, missing redirect URIs, PKCE not required, Direct access grants left on, a missing service account role, and even a single space in a curl command.
