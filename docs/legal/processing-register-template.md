# Register över behandling (RoPA) – mall

Uppdatera denna löpande och använd den internt.

## Fält
- Behandling
- Ändamål
- Kategorier av registrerade
- Kategorier av personuppgifter
- Rättslig grund (GDPR art. 6)
- Mottagare/underbiträden
- Tredjelandsöverföring
- Lagringstid
- Tekniska/organisatoriska skydd
- Ansvarig ägare
- Senast uppdaterad

## Exempelposter

### 1) Inloggning och sessionshantering
- Behandling: Autentisering till dashboard
- Ändamål: Ge kontrollerad åtkomst
- Registrerade: Kunder/användare
- Uppgifter: Användarnamn, sessions-id, säkerhetsloggar
- Rättslig grund: Avtal / berättigat intresse
- Mottagare: Hosting-leverantör
- Lagringstid: Session upp till 12h, loggar normalt 90 dagar
- Skydd: Hashade lösenord, rate-limit, httpOnly-cookie

### 2) Samtyckeshantering (om icke-nödvändig spårning används)
- Behandling: Spara samtyckesval
- Ändamål: Visa/blockera optional tracking korrekt
- Registrerade: Webbplatsbesökare
- Uppgifter: Samtyckesstatus
- Rättslig grund: Samtycke / rättslig skyldighet
- Lagringstid: Tills radering eller policygräns
- Skydd: Lokal lagring, minimera data
