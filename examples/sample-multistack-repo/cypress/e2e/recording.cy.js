describe("Recording feature", () => {
  it("shows a countdown before recording starts @recording", () => {
    expect(true).to.eq(true);
  });

  // tags: recording
  it("allows pausing and resuming an active recording", () => {
    expect(true).to.eq(true);
  });

  it("uploads the finished recording to the cloud @recording @upload", () => {
    expect(true).to.eq(true);
  });

  // depends-on: shows a countdown before recording starts
  // (this test assumes a recording is already in progress from the test above)
  it("shows an error if storage is full while recording", () => {
    expect(true).to.eq(true);
  });

  // No title/tag mentions "recording" -- nltest finds this one via its body.
  it("renders the correct button icon", () => {
    cy.get("[data-testid=recording-toggle-button]").should("be.visible");
  });
});

describe("Login", () => {
  it("logs the user in with valid credentials @login", () => {
    expect(true).to.eq(true);
  });
});
