import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import { ImageGallery, type ImageCard } from "@/components/chat/image-gallery";
import { ImageFileGrid, isImageFileCard, type FileCard } from "@/components/chat/file-card";

vi.mock("@/lib/api-base", () => ({
  getApiUrl: () => "http://127.0.0.1:8900/api",
  getAuthToken: () => "test-token",
  assetUrl: (p: string) => `http://127.0.0.1:8900/api/${p}`,
}));

vi.mock("@/components/preview-panel/preview-context", () => ({
  usePreview: () => ({ open: vi.fn() }),
}));

vi.mock("@ethan/shared/ppt/preview", () => ({
  signFileUrl: vi.fn(async (_api: string, _tok: string, paths: string[]) =>
    Object.fromEntries(paths.map((p) => [p, { user: "u1", sig: "sig123" }])),
  ),
}));

function makeImageCard(i: number): ImageCard {
  return {
    type: "image",
    title: `img-${i}`,
    url: `https://example.com/${i}.jpg`,
    local_path: "",
    source: "web",
    page_url: "",
    width: null,
    height: null,
    size_kb: null,
  };
}

function makeImageFileCard(i: number, kind = "png"): FileCard {
  return {
    type: "file",
    filename: `shot-${i}.${kind}`,
    path: `/tmp/shot-${i}.${kind}`,
    size_kb: 120,
    kind,
  };
}

describe("ImageGallery multi-image grid", () => {
  it("renders 2 images in a 2-column cropped grid with uniform gap", () => {
    const { container } = render(<ImageGallery cards={[makeImageCard(1), makeImageCard(2)]} />);
    const grid = container.querySelector(".grid");
    expect(grid?.className).toContain("grid-cols-2");
    expect(grid?.className).toContain("gap-2");
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    imgs.forEach((img) => {
      expect(img.className).toContain("object-cover");
      expect(img.className).toContain("my-0");
    });
  });

  it("renders 5 images in a 3-column cropped grid with uniform gap", () => {
    const cards = [1, 2, 3, 4, 5].map(makeImageCard);
    const { container } = render(<ImageGallery cards={cards} />);
    const grid = container.querySelector(".grid");
    expect(grid?.className).toContain("grid-cols-3");
    expect(grid?.className).toContain("gap-2");
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(5);
    imgs.forEach((img) => {
      expect(img.className).toContain("object-cover");
      expect(img.className).toContain("w-full");
      expect(img.className).toContain("h-full");
    });
  });
});

describe("ImageFileGrid delivered image layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("classifies image vs non-image file cards accurately", () => {
    expect(isImageFileCard(makeImageFileCard(1, "PNG"))).toBe(true);
    expect(isImageFileCard(makeImageFileCard(2, "webp"))).toBe(true);
    expect(isImageFileCard(makeImageFileCard(3, "pdf"))).toBe(false);
  });

  it("signs 101 image paths in batches below the backend limit", async () => {
    const signer = vi.mocked(signFileUrl);
    signer.mockImplementation(async (_api, _token, paths) => {
      if (paths.length > 100) return {};
      return Object.fromEntries(paths.map((p) => [p, { user: "u1", sig: "sig123" }]));
    });
    const cards = Array.from({ length: 101 }, (_, i) => makeImageFileCard(i));
    const { container } = render(<ImageFileGrid cards={cards} sessionId="s1" />);
    await waitFor(() => expect(container.querySelectorAll("img")).toHaveLength(101));
    expect(signer.mock.calls.map((call) => call[2].length)).toEqual([100, 1]);
  });

  it("renders 4 delivered images in a 3-column filled square grid", async () => {
    const cards = [1, 2, 3, 4].map((i) => makeImageFileCard(i));
    const { container } = render(<ImageFileGrid cards={cards} sessionId="s1" />);

    await waitFor(() => {
      expect(container.querySelectorAll("img")).toHaveLength(4);
    });

    const grid = container.querySelector('[data-slot="image-file-grid"]');
    expect(grid?.className).toContain("grid-cols-3");
    expect(grid?.className).toContain("gap-2");
    container.querySelectorAll("img").forEach((img) => {
      expect(img.className).toContain("object-cover");
      expect(img.className).toContain("my-0");
    });
  });
});
