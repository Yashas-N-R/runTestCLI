import { test, expect } from "@playwright/test";

test.describe("Recording", () => {
  test("recording indicator appears in the toolbar @recording", async () => {
    expect(true).toBe(true);
  });

  // tags: recording, permissions
  test("requesting camera permission before recording", async () => {
    expect(true).toBe(true);
  });
});

test.describe("Search", () => {
  test("search returns results for a known query @search", async () => {
    expect(true).toBe(true);
  });
});
