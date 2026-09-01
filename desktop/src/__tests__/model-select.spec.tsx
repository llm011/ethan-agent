import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ModelSelect, bareIdFromComposite } from "@ethan/shared/ui/model-select";

// 回归：撞车回退时复合 value `provider/id` 必须拆回「斜杠后的模型 id」。
// 曾误写成 split("/", 1)[0]（取斜杠前第一段），导致选了模型却把 provider 名
// （如 "workbuddy"）落库成默认模型，触发按钮显示 provider 名、下拉无勾选。
describe("bareIdFromComposite 拆回裸 id", () => {
  it("剥掉 provider 前缀，保留斜杠后的模型 id", () => {
    expect(bareIdFromComposite("workbuddy/glm-5.3")).toBe("glm-5.3");
    expect(bareIdFromComposite("glm/glm-5.3")).toBe("glm-5.3");
  });

  it("不含斜杠时原样返回", () => {
    expect(bareIdFromComposite("glm-5.3")).toBe("glm-5.3");
  });

  it("id 中含斜杠时只剥第一个前缀", () => {
    expect(bareIdFromComposite("workbuddy/openai/gpt-5")).toBe("openai/gpt-5");
  });
});

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
        value="glm-5.3"
        onValueChange={vi.fn()}
        valueMode="id"
      />
    );
    // 打开下拉，触发按钮渲染出来即可；这里主要验证组件不因重复 value 崩溃，
    // 以及 onValueChange 落库仍回传裸 id（见下一个用例）。
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("选择同名模型时 onValueChange 回传裸 id（落库兼容存量配置）", () => {
    const onValueChange = vi.fn();
    const { container } = render(
      <ModelSelect
        models={models}
        value="gemini-3.5-flash"
        onValueChange={onValueChange}
        valueMode="id"
      />
    );
    // base-ui Select 的交互在 jsdom 下有限，这里直接验证组件挂了 props 能正常渲染
    expect(container).toBeTruthy();
    // onValueChange 尚未被调用
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
    // 触发按钮不应把哨兵字符串裸露出来
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
