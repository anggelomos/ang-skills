// The pairing page: auto-submits once six characters are in. Without JavaScript, Enter submits the form.
const form = document.querySelector("form"), root = document.querySelector(".code"), input = root.querySelector("input");
const slots = [...root.querySelectorAll(".slot")], status = document.querySelector(".status");
const say = (cls, html) => { status.className = "status" + (cls ? " " + cls : ""); status.innerHTML = html; };
const paint = () => {
  const v = input.value, focused = document.activeElement === input;
  slots.forEach((s, i) => {
    s.textContent = v[i] || "";
    s.classList.toggle("is-active", focused && i === Math.min(v.length, 5));
  });
};
const toEnd = () => requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
input.addEventListener("focus", () => { toEnd(); paint(); });
input.addEventListener("click", toEnd);
input.addEventListener("keyup", toEnd);
input.addEventListener("blur", paint);
input.addEventListener("input", () => {
  // uppercase and keep only characters codes use, so a pasted "j59-t88" becomes J59T88
  input.value = input.value.toUpperCase().replace(/[^ABCDEFGHJKMNPQRSTUVWXYZ23456789]/g, "").slice(0, 6);
  if (root.classList.contains("is-error")) { root.classList.remove("is-error"); say("", ""); }
  paint();
  if (input.value.length === 6) send();
});
form.addEventListener("submit", (e) => { e.preventDefault(); if (input.value.length === 6) send(); });
async function send() {
  const body = new URLSearchParams(new FormData(form)); // before disabling: disabled fields aren't sent
  input.disabled = true;
  say("", 'Checking <span class="loader"><i></i><i></i><i></i></span>');
  let r, data = {};
  try {
    r = await fetch("/pair", { method: "POST", headers: { Accept: "application/json" }, body });
    data = await r.json();
  } catch (e) { data.error = "Couldn't reach the hub. Try again."; }
  if (r && r.ok) {
    root.classList.add("is-ok");
    say("is-ok", "Paired. Opening…");
    return setTimeout(() => location.replace(data.next), 400);
  }
  root.classList.add("is-error");
  root.classList.remove("shake"); void root.offsetWidth; root.classList.add("shake");
  say("is-error", data.error || "Something went wrong.");
  setTimeout(() => { input.value = ""; input.disabled = false; paint(); input.focus(); }, 700);
}
input.disabled = false;
input.focus();
paint();
