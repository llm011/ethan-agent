# 数据绑定、模板列表与函数（A2UI v0.9.1）

简单卡片直接写字面量即可，不必用绑定。需要动态数据、列表、表单交互时才看这里。

## JSON Pointer 数据绑定

任何 `Dynamic*` 字段都能写成 `{"path":"/json/pointer"}`，从 `updateDataModel` 设的数据模型取值。

- **绝对路径**：`/` 开头，从数据模型根解析，如 `{"path":"/user/name"}`。
- **相对路径**：不带 `/`，仅在模板内（容器用 `children:{path,componentId}` 迭代数组时）有效，解析为「当前项」的字段，如模板里 `{"path":"name"}` 对 `/users` 迭代时解析成 `/users/0/name`、`/users/1/name`…
- 取不到值时按空串渲染（支持渐进渲染，updateDataModel 后到也行）。

## 模板列表

容器（Column/Row/List）的 `children` 可以不是 id 数组，而是模板对象：

```json
{"id":"list","component":"Column","children":{"path":"/items","componentId":"tpl"}}
```

客户端对 `/items` 数组每一项实例化一次 `tpl` 组件，模板内用相对路径取该项字段。见 examples.md 示例 4。

## 双向绑定（表单）

输入组件（TextField / CheckBox / Slider / ChoicePicker / DateTimeInput）的 `value` 绑定到某路径后是**双向**的：用户输入立即写回本地数据模型；同路径的其它组件实时联动。

输入**不会**自动发请求；只有点 Button（action）时，才把 action.context 里引用的路径解析成当前值发回 agent。表单提交模式：

```json
{"id":"email","component":"TextField","label":"邮箱","value":{"path":"/form/email"}},
{"id":"submit","component":"Button","child":"submit-label","action":{"event":{"name":"submit","context":{"email":{"path":"/form/email"}}}}},
{"id":"submit-label","component":"Text","text":"提交"}
```

## 常用函数（在 Dynamic 字段里用 `{"call":"fn","args":{…}}`）

- `formatString` — 字符串插值：`{"call":"formatString","args":{"value":"你好 ${/user/name}"}}`。`${...}` 包路径或 `fn()`。
- `formatNumber` / `formatCurrency`（`args.currency` 如 `"CNY"`）/ `formatDate`（`args.format`）。
- 校验（放进输入组件的 `checks` 数组，失败显示 message）：`required` `regex`(args.pattern) `email` `length` `numeric`。
- 逻辑：`and` `or` `not`（args.values 数组）。
- `openUrl`（本地动作，args.url）。

校验示例：
```json
{"id":"email","component":"TextField","label":"邮箱","value":{"path":"/form/email"},
 "checks":[
   {"call":"required","args":{"value":{"path":"/form/email"}},"message":"邮箱必填"},
   {"call":"email","args":{"value":{"path":"/form/email"}},"message":"邮箱格式不对"}
 ]}
```

Button 的 `checks` 失败时按钮自动禁用——可用来做「填完才能提交」。
