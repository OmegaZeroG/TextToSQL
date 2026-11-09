import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

import Button from "./ui/Button";
import Icon from "./ui/Icon";

interface State {
  failed: boolean;
}

/** Catches render errors so one bug shows a recovery screen instead of a blank page. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI crashed:", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="grid min-h-screen place-items-center p-6">
        <div className="max-w-sm rounded-lg border border-border bg-card p-6 text-center shadow-card">
          <Icon name="alert" className="mx-auto size-8 text-destructive" />
          <h1 className="mt-3 text-lg font-semibold">Something broke</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            The page hit an unexpected error. Your saved schema is safe in this browser.
          </p>
          <Button variant="primary" className="mt-4" onClick={() => window.location.reload()}>
            Reload the page
          </Button>
        </div>
      </div>
    );
  }
}
