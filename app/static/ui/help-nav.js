// v0.4.3 #8 (part-timer): the help page shows the app menu only when signed in; signed out it offers "Sign in".
fetch("/api/me", {credentials: "same-origin"}).then(r => {
  if (!r.ok) return;
  const n = document.getElementById("helpNav"), b = document.getElementById("helpBack");
  if (n) n.hidden = false;
  if (b) b.textContent = "← Back to the scanner";
}).catch(() => {});
