// Business details shown on every page. Edit these values once before publishing.
const CONFIG = {
  brand: "MatchDesk",
  legalName: "[Legal business name]",            // e.g. the registered name of your company
  address: "[Business mailing address], Vancouver, BC, Canada",
  email: "hello@example.com",                   // general contact and sales
  privacyEmail: "privacy@example.com",          // can be the same mailbox
  privacyOfficer: "[Name of the person responsible for privacy]",
  hostingProvider: "Contabo",
  hostingCountry: "[country of your server]",
  emailProvider: "Hostinger",
  updated: "[date you publish]"
};

document.querySelectorAll("[data-cfg]").forEach(el => { el.textContent = CONFIG[el.dataset.cfg]; });
document.querySelectorAll("[data-cfg-mail]").forEach(el => {
  const key = el.dataset.cfgMail || "email";
  el.href = "mailto:" + CONFIG[key];
  if (!el.textContent.trim()) el.textContent = CONFIG[key];
});
