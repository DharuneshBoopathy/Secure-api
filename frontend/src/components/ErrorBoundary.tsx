import { Component, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900">
          Something went wrong while rendering this page. Refresh and try again.
        </div>
      );
    }
    return this.props.children;
  }
}
