const views = {
  fly: {
    title: "Fly with fewer distractions",
    description:
      "Attitude, key telemetry, map, and essential flight actions. Additional controls and video open only when you need them.",
  },
  plan: {
    title: "Build and verify your mission",
    description:
      "Edit mission items, generate survey lines, and import or export supported plans. The desktop app verifies transfers through readback. Screenshot includes an illustrative local draft.",
  },
  vehicle: {
    title: "Inspect your vehicle settings",
    description:
      "Find parameters quickly and review changes before restoring a backup. Desktop writes wait for matching controller readback. Parameter values shown here are illustrative.",
  },
  analyze: {
    title: "Understand the flight",
    description:
      "Compare telemetry curves, inspect the event timeline, and export CSV data. Historical log review is separate from live vehicle control. Screenshot curves are sample data.",
  },
  settings: {
    title: "Set it up for your workflow",
    description:
      "Choose appearance, video sources, battery alert thresholds, and offline maps. Preferences have a dedicated screen.",
  },
  diagnostics: {
    title: "Go deeper without crowding Fly",
    description:
      "Stream freshness, trend plots, and command acknowledgments live here. Open the same diagnostics in a second window for another display.",
  },
};
document.querySelectorAll("[data-workspace]").forEach((button) =>
  button.addEventListener("click", () => {
    const name = button.dataset.workspace,
      view = views[name];
    document
      .querySelectorAll("[data-workspace]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    const image = document.querySelector("#workspace-image");
    image.src = `design/${name}-workspace.png`;
    image.alt = `Actual PythonGCS ${name} workspace. ${view.description}`;
    document.querySelector("#workspace-title").textContent = view.title;
    document.querySelector("#workspace-description").textContent =
      view.description;
  }),
);
