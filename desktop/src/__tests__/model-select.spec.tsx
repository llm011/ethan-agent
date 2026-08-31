import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ModelSelect } from "@ethan/shared/components/model-select";

const MODELS = [
  { id: "claude-sonnet-4.6", description: "Sonnet 4.6", provider: "anthropic" },
  { id: "gpt-5", description: "GPT-5", provider: "openai" },
  { id: "no-provider", description: "裸模型" },
];

function openMenu() {
  const trigger = screen.getByRole("combobox");
  fireEvent.pointerDown(trigger, { pointerType: "mouse", button: 0 });
  fireEvent.mouseDown(trigger, { button: 0 });
  fireEvent.pointerUp(trigger, { pointerType: "mouse", button: 0 });
  fireEvent.mouseUp(trigger, { button: 0 });
  fireEvent.click(trigger, { button: 0 });
  return trigger;
}

// base-ui 的 Select.Item 靠 pointerup/click 组合触发选中，裸 click 不足以走通
function pickItem(item: HTMLElement) {
  fireEvent.pointerDown(item, { pointerType: "mouse", button: 0 });
  fireEvent.mouseDown(item, { button: 0 });
  fireEvent.pointerUp(item, { pointerType: "mouse", button: 0 });
  fireEvent.mouseUp(item, { button: 0 });
  fireEvent.click(item, { button: 0 });
}

describe("ModelSelect", () => {
  it("trigger 上把 provider 作为前缀和模型名一起展示（inline 形态）", () => {
    render(
      <ModelSelect variant="inline" models={MODELS} value="claude-sonnet-4.6" onChange={vi.fn()} />
    );
    const trigger = screen.getByRole("combobox");
    expect(trigger.textContent).toContain("anthropic");
    expect(trigger.textContent).toContain("Sonnet 4.6");
  });

  it("trigger 上把 provider 作为前缀和模型名一起展示（form 形态）", () => {
    render(<ModelSelect variant="form" models={MODELS} value="gpt-5" onChange={vi.fn()} />);
    const trigger = screen.getByRole("combobox");
    expect(trigger.textContent).toContain("openai");
    expect(trigger.textContent).toContain("GPT-5");
  });

  it("模型没有 provider 时只展示模型名，不出现空前缀", () => {
    render(<ModelSelect models={MODELS} value="no-provider" onChange={vi.fn()} />);
    const trigger = screen.getByRole("combobox");
    expect(trigger.textContent).toContain("裸模型");
    expect(trigger.textContent).not.toContain("anthropic");
    expect(trigger.textContent).not.toContain("openai");
  });

  it("未命中模型时回退到 placeholder", () => {
    render(<ModelSelect models={MODELS} value="" onChange={vi.fn()} placeholder="模型" />);
    expect(screen.getByRole("combobox").textContent).toContain("模型");
  });

  it("展开后每个选项都带 provider 前缀，选中回传 model id", async () => {
    const onChange = vi.fn();
    render(<ModelSelect models={MODELS} value="gpt-5" onChange={onChange} />);

    openMenu();

    const items = await screen.findAllByRole("option");
    const texts = items.map((el) => el.textContent ?? "");
    expect(texts.some((t) => t.includes("anthropic") && t.includes("Sonnet 4.6"))).toBe(true);
    expect(texts.some((t) => t.includes("openai") && t.includes("GPT-5"))).toBe(true);

    const target = items.find((el) => (el.textContent ?? "").includes("Sonnet 4.6"))!;
    pickItem(target);
    expect(onChange).toHaveBeenCalledWith("claude-sonnet-4.6");
  });

  it("emptyOption 存在时可以选回空值（轻量模型「留空」）", async () => {
    const onChange = vi.fn();
    render(
      <ModelSelect
        models={MODELS}
        value="gpt-5"
        onChange={onChange}
        emptyOption={{ value: "", label: "留空（自动推断）" }}
      />
    );

    openMenu();

    const items = await screen.findAllByRole("option");
    const empty = items.find((el) => (el.textContent ?? "").includes("留空"))!;
    pickItem(empty);
    expect(onChange).toHaveBeenCalledWith("");
  });
});
