import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AiModels } from "@/api/client";
import { AI_SETTINGS, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { AiCard } from "./ai";

const MODELS: AiModels = {
  backend: "openai",
  server: AI_SETTINGS.server,
  models: [
    { id: "qwen-tiny", kind: "vlm", loaded: true, detail: "mlx · 8bit" },
    { id: "qwen-big", kind: "llm", loaded: false, detail: null },
  ],
  error: null,
};

describe("the AI settings", () => {
  it("checks the server and saves only what changed", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    const { requests } = mockApi({
      "GET /api/ai": AI_SETTINGS,
      "POST /api/ai/models": MODELS,
      "PATCH /api/ai": async (request: Request) => {
        const patch = await request.json();
        patches.push(patch);
        return { ...AI_SETTINGS, ...patch };
      },
    });
    renderWithProviders(<AiCard />);

    expect(await screen.findByText("Connected · 2 models")).toBeInTheDocument();
    const listed = requests.find((r) => r.url.endsWith("/api/ai/models"));
    expect(await listed?.json()).toEqual({ backend: "openai", server: AI_SETTINGS.server });
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();

    const names = screen.getAllByRole("textbox", { name: "Label name" });
    await user.clear(names[1] as HTMLElement);
    await user.type(names[1] as HTMLElement, "Drug");
    await user.type(
      screen.getAllByRole("textbox", { name: "Label examples" })[1] as HTMLElement,
      "aspirin, ",
    );
    await user.click(save);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({
      labels: [
        { name: "Condition", description: "Diseases", examples: ["dementia"], color: "red" },
        { name: "Drug", description: "", examples: ["aspirin"], color: "blue" },
      ],
    });
    await waitFor(() => expect(save).toBeDisabled());
  });

  it("won't save labels without names, or with the same name", async () => {
    const user = userEvent.setup();
    mockApi({ "GET /api/ai": AI_SETTINGS, "POST /api/ai/models": MODELS });
    renderWithProviders(<AiCard />);

    await user.click(await screen.findByRole("button", { name: "Add label" }));
    expect(await screen.findByText("Every label needs a name.")).toBeInTheDocument();
    const names = screen.getAllByRole("textbox", { name: "Label name" });
    await user.type(names[2] as HTMLElement, "condition");
    expect(screen.getByText("Label names must differ.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getAllByRole("textbox", { name: "Label name" })).toHaveLength(2);
  });

  it("says why it can't reach the server", async () => {
    mockApi({
      "GET /api/ai": { ...AI_SETTINGS, locked: ["server"] },
      "POST /api/ai/models": {
        ...MODELS,
        models: [],
        error: "can't reach the model server at http://127.0.0.1:1234/v1; is it running?",
      },
    });
    renderWithProviders(<AiCard />);

    expect(await screen.findByText(/is it running\?/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Server" })).toBeDisabled();
  });
});
