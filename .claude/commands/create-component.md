---
description: Create a new React component following QPrisma frontend patterns
---

# Create React Component

Create a new React component following QPrisma frontend patterns.

## Usage
```
/create-component <ComponentName> [--type page|feature|ui] [--path <path>]
```

## Instructions

When creating a new React component for QPrisma, follow these patterns:

### 1. Create the component file at `frontend/components/{path}/{ComponentName}.tsx`

```tsx
'use client';

/**
 * {ComponentName}
 *
 * {Description of the component's purpose}
 */

import { useState, useEffect, useCallback } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';

// =============================================================================
// Types
// =============================================================================

interface {ComponentName}Props {
  /** Unique identifier */
  id?: string;
  /** Optional CSS class name */
  className?: string;
  /** Callback when action completes */
  onComplete?: (result: {ComponentName}Result) => void;
  /** Callback on error */
  onError?: (error: Error) => void;
}

interface {ComponentName}Result {
  success: boolean;
  data?: unknown;
}

interface {ComponentName}State {
  loading: boolean;
  error: string | null;
  data: unknown | null;
}

// =============================================================================
// Component
// =============================================================================

export function {ComponentName}({
  id,
  className = '',
  onComplete,
  onError,
}: {ComponentName}Props) {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const [state, setState] = useState<{ComponentName}State>({
    loading: false,
    error: null,
    data: null,
  });

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------
  const handleAction = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/endpoint`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      setState(prev => ({ ...prev, loading: false, data }));
      onComplete?.({ success: true, data });

    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      setState(prev => ({ ...prev, loading: false, error: err.message }));
      onError?.(err);
    }
  }, [id, onComplete, onError]);

  // ---------------------------------------------------------------------------
  // Effects
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Initial load or setup
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const { loading, error, data } = state;

  if (loading) {
    return (
      <div className={`flex items-center justify-center p-8 ${className}`}>
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
        <span className="ml-2 text-gray-600">Loading...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`flex items-center p-4 bg-red-50 rounded-lg ${className}`}>
        <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
        <span className="text-red-700">{error}</span>
      </div>
    );
  }

  return (
    <div className={`p-4 ${className}`}>
      {/* Component content */}
      <h2 className="text-xl font-semibold text-gray-900">
        {ComponentName}
      </h2>

      <button
        onClick={handleAction}
        className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg
                   hover:bg-blue-700 transition-colors disabled:opacity-50"
        disabled={loading}
      >
        Action
      </button>
    </div>
  );
}

export default {ComponentName};
```

### 2. Export from `frontend/components/index.ts`

```typescript
export { {ComponentName} } from './{path}/{ComponentName}';
```

### 3. Component Patterns by Type

**Page Component** (full page with layout):
```tsx
// Located at: frontend/app/{route}/page.tsx
export default function {ComponentName}Page() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <{ComponentName} />
      </div>
    </main>
  );
}
```

**Feature Component** (complex with state):
- Use custom hooks for data fetching
- Implement loading/error states
- Support callbacks for parent communication

**UI Component** (presentational):
```tsx
// Stateless, receives all data via props
interface {ComponentName}Props {
  title: string;
  children: React.ReactNode;
}

export function {ComponentName}({ title, children }: {ComponentName}Props) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <h3 className="font-medium text-gray-900">{title}</h3>
      {children}
    </div>
  );
}
```

### 4. Using SWR for Data Fetching

```tsx
import useSWR from 'swr';

const fetcher = (url: string) => fetch(url).then(res => res.json());

export function {ComponentName}({ mediaId }: { mediaId: string }) {
  const { data, error, isLoading, mutate } = useSWR(
    mediaId ? `${process.env.NEXT_PUBLIC_API_URL}/media/${mediaId}` : null,
    fetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  // Use mutate() to refresh data after mutations
  const handleUpdate = async () => {
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/media/${mediaId}`, {
      method: 'PATCH',
      // ...
    });
    mutate(); // Revalidate the cache
  };

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorDisplay error={error} />;

  return <div>{/* Use data */}</div>;
}
```

### 5. Video Player Integration

```tsx
import { useRef, useCallback } from 'react';

export function VideoComponent({ mediaId }: { mediaId: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  const seekTo = useCallback((timestamp: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = timestamp;
      videoRef.current.play();
    }
  }, []);

  return (
    <video
      ref={videoRef}
      src={`${process.env.NEXT_PUBLIC_API_URL}/media/${mediaId}/stream`}
      controls
      className="w-full rounded-lg"
    />
  );
}
```

### 6. Create tests at `frontend/__tests__/{ComponentName}.test.tsx`

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { {ComponentName} } from '@/components/{path}/{ComponentName}';

describe('{ComponentName}', () => {
  it('renders correctly', () => {
    render(<{ComponentName} />);
    expect(screen.getByText('{ComponentName}')).toBeInTheDocument();
  });

  it('handles action click', async () => {
    const onComplete = jest.fn();
    render(<{ComponentName} onComplete={onComplete} />);

    fireEvent.click(screen.getByRole('button', { name: /action/i }));

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalled();
    });
  });

  it('displays error state', () => {
    // Mock fetch to return error
    global.fetch = jest.fn().mockRejectedValue(new Error('Test error'));

    render(<{ComponentName} />);
    // Trigger action and verify error display
  });
});
```

## Styling Guidelines

- Use Tailwind CSS for all styling
- Follow responsive design: `sm:`, `md:`, `lg:` prefixes
- Use semantic colors: `text-gray-900`, `bg-blue-600`, etc.
- Consistent spacing: `p-4`, `gap-4`, `space-y-4`
- Lucide React for icons

## Checklist
- [ ] Component file created with TypeScript
- [ ] Props interface defined with JSDoc comments
- [ ] Loading state handled
- [ ] Error state handled
- [ ] Exported from components/index.ts
- [ ] Tests created
- [ ] Responsive design implemented
- [ ] Accessibility considered (aria labels, keyboard navigation)
