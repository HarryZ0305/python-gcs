const screens = await fetch("screens.json?v=4").then((response) => {
  if (!response.ok) throw Error("Screen guide unavailable");
  return response.json();
});
const select = document.getElementById("screen-select");
screens.forEach((screen) => {
  const option = document.createElement("option");
  option.value = screen.slug;
  option.textContent = screen.title;
  select.append(option);
});
function showScreen() {
  let index = screens.findIndex(
    (screen) => screen.slug === location.hash.slice(1),
  );
  if (index < 0) index = 0;
  const screen = screens[index];
  select.value = screen.slug;
  document.getElementById("screen-title").textContent = screen.title;
  document.getElementById("screen-path").textContent = screen.path;
  document.getElementById("screen-note").textContent = screen.note;
  const image = document.getElementById("screen-image");
  image.src = `images/${screen.slug}.png`;
  image.alt = `${screen.title}. Labeled features: ${screen.features.map((feature) => feature.title).join(", ")}.`;
  const list = document.getElementById("screen-features");
  list.replaceChildren();
  screen.features.forEach((feature) => {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = feature.title;
    item.append(title, document.createTextNode(feature.detail));
    list.append(item);
  });
  document.getElementById("previous-screen").disabled = index === 0;
  document.getElementById("next-screen").disabled =
    index === screens.length - 1;
  document.getElementById("screen-count").textContent =
    `${index + 1} / ${screens.length}`;
}
select.addEventListener("change", () => {
  location.hash = select.value;
});
document.getElementById("previous-screen").addEventListener("click", () => {
  location.hash = screens[Math.max(0, select.selectedIndex - 1)].slug;
});
document.getElementById("next-screen").addEventListener("click", () => {
  location.hash =
    screens[Math.min(screens.length - 1, select.selectedIndex + 1)].slug;
});
window.addEventListener("hashchange", showScreen);
showScreen();
