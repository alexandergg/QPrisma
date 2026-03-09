/**
 * Tests for components/ErrorBoundary.tsx
 *
 * Covers:
 * - Renders children normally when no error
 * - Catches errors and renders fallback UI
 * - Custom fallback component
 * - Try Again button resets error state
 * - onError callback is called
 * - showDetails reveals error information
 * - withErrorBoundary HOC
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary, withErrorBoundary } from './ErrorBoundary';

// Suppress console.error during error boundary tests
const originalError = console.error;
beforeAll(() => {
  console.error = jest.fn();
});
afterAll(() => {
  console.error = originalError;
});

// A component that always throws
function ThrowingComponent({ shouldThrow = true }: { shouldThrow?: boolean }) {
  if (shouldThrow) {
    throw new Error('Test error');
  }
  return <div>No error</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div>Hello</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('renders default error UI when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Try Again')).toBeInTheDocument();
    expect(screen.getByText('Go Home')).toBeInTheDocument();
  });

  it('renders custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<div>Custom Error</div>}>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Custom Error')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('calls onError callback when error occurs', () => {
    const onError = jest.fn();
    render(
      <ErrorBoundary onError={onError}>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({ componentStack: expect.any(String) }),
    );
  });

  it('resets error state when Try Again is clicked', () => {
    let shouldThrow = true;

    function ConditionalThrow() {
      if (shouldThrow) {
        throw new Error('Boom');
      }
      return <div>Recovered</div>;
    }

    render(
      <ErrorBoundary>
        <ConditionalThrow />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    // Fix the error before retrying
    shouldThrow = false;

    fireEvent.click(screen.getByText('Try Again'));
    expect(screen.getByText('Recovered')).toBeInTheDocument();
  });

  it('shows error details when showDetails is true', () => {
    render(
      <ErrorBoundary showDetails={true}>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Error details')).toBeInTheDocument();
  });

  it('does not show error details by default', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.queryByText('Error details')).not.toBeInTheDocument();
  });
});

describe('withErrorBoundary', () => {
  it('wraps component with error boundary', () => {
    function GoodComponent() {
      return <div>Wrapped content</div>;
    }

    const Wrapped = withErrorBoundary(GoodComponent);
    render(<Wrapped />);

    expect(screen.getByText('Wrapped content')).toBeInTheDocument();
  });

  it('catches errors in wrapped component', () => {
    const Wrapped = withErrorBoundary(ThrowingComponent);
    render(<Wrapped />);

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('sets correct displayName', () => {
    function MyComponent() {
      return <div>Test</div>;
    }

    const Wrapped = withErrorBoundary(MyComponent);
    expect(Wrapped.displayName).toBe('WithErrorBoundary(MyComponent)');
  });
});
