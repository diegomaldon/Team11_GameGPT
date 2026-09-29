// @vitest-environment jsdom

import { useState } from "react";
import { describe, expect, it, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal, TextInput } from "./ui";

afterEach(cleanup);

// Mirrors how DangerCard uses Modal: an onClose declared in the parent body, so it is
// a different function on every render, plus a controlled input that re-renders the
// parent on every keystroke. That combination is what broke focus.
function Host() {
  const [open, setOpen] = useState(true);
  const [typed, setTyped] = useState("");

  function closeModal() {
    setOpen(false);
  }

  return (
    <Modal open={open} onClose={closeModal} title="Delete account?">
      <TextInput
        id="confirm"
        aria-label="confirm"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />
    </Modal>
  );
}

describe("Modal", () => {
  it("keeps focus in a controlled input across keystrokes", async () => {
    const user = userEvent.setup();
    render(<Host />);

    const input = screen.getByLabelText("confirm") as HTMLInputElement;
    await user.click(input);
    await user.keyboard("DELETE");

    // Without the ref, the focus effect re-ran on each render and only the first
    // character landed.
    expect(input.value).toBe("DELETE");
    expect(document.activeElement).toBe(input);
  });

  it("still closes on Escape after the parent has re-rendered", async () => {
    const user = userEvent.setup();
    render(<Host />);

    const input = screen.getByLabelText("confirm");
    await user.click(input);
    await user.keyboard("DEL");

    // The Escape handler reads onClose through a ref, so it must still see the
    // current one rather than the closure captured when the modal opened.
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
