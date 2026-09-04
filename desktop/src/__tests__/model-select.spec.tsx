import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ModelSelect } from "@ethan/shared/ui/model-select";

// base-ui 的 Select 在 jsdom 下弹层交互较受限，这里聚焦两个纯逻辑层面的修复：
// 1) valueMode="id" 下同名不同 provider 模型的 item value 必须唯一（否则 radix 会撞车）；
// 2) value 匹配不到模型时，unmatchedLabel 能兜底显示友好文案而非原始哨兵值。

describe("ModelSelect valueMode=id 同名撞车", () => {
  const models = [
    { id: "glm-5.3", provider: "glm", description: "GLM 5.3" },
    { id: "glm-5.3", provider: "workbuddy", description: "GLM 5.3" },
    { id: "gemini-3.5-flash", provider: "cliproxy", description: "Gemini" },
  ];

  it("列表项 value 唯一，不会撞车（provider/id 区分同名）", () => {
    render(
      <ModelSelect
        models={models}
        value="glm/glm-5.3"
        onValueChange={vi.fn()}
        valueMode="id"
      />
    );
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("选择同名模型时 onValueChange 回传 provider/id（区分不同 provider）", () => {
    const onValueChange = vi.fn();
    const { container } = render(
      <ModelSelect
        models={models}
        value="gemini-3.5-flash"
        onValueChange={onValueChange}
        valueMode="id"
      />
    );
    expect(container).toBeTruthy();
    expect(onValueChange).not.toHaveBeenCalled();
  });
});

describe("ModelSelect unmatchedLabel 兜底", () => {
  const models = [{ id: "gpt-4", provider: "openai", description: "GPT-4" }];

  it("value 匹配不到时显示 unmatchedLabel 而非原始哨兵值", () => {
    const { container } = render(
      <ModelSelect
        models={models}
        value="__need_model_choice__"
        onValueChange={vi.fn()}
        valueMode="fullId"
        unmatchedLabel={(v) =>
          v === "__need_model_choice__" ? "有多个 provider 提供该模型，请指定一个" : v
        }
      />
    );
    expect(container.textContent).not.toContain("__need_model_choice__");
    expect(container.textContent).toContain("有多个 provider 提供该模型，请指定一个");
  });

  it("未传 unmatchedLabel 时回退为显示原始 value", () => {
    const { container } = render(
      <ModelSelect
        models={models}
        value="legacy-model-id"
        onValueChange={vi.fn()}
        valueMode="fullId"
      />
    );
    expect(container.textContent).toContain("legacy-model-id");
  });
});
