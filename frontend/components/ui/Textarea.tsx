import React, { forwardRef, memo, useCallback, useId, useRef } from 'react';

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  helperText?: string;
  autoResize?: boolean;
}

const Textarea = memo(
  forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
    {
      label,
      error,
      helperText,
      autoResize = false,
      className = '',
      id: externalId,
      onInput,
      ...rest
    },
    ref,
  ) {
    const generatedId = useId();
    const inputId = externalId ?? generatedId;
    const hasError = Boolean(error);
    const internalRef = useRef<HTMLTextAreaElement | null>(null);

    const handleRef = useCallback(
      (node: HTMLTextAreaElement | null) => {
        internalRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = node;
      },
      [ref],
    );

    const handleInput = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        if (autoResize && internalRef.current) {
          internalRef.current.style.height = 'auto';
          internalRef.current.style.height = `${internalRef.current.scrollHeight}px`;
        }
        onInput?.(e);
      },
      [autoResize, onInput],
    );

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="text-sm font-medium text-[var(--foreground)]"
          >
            {label}
          </label>
        )}
        <textarea
          ref={handleRef}
          id={inputId}
          onInput={handleInput}
          className={`w-full rounded-[var(--radius-md)] bg-[var(--surface)] border border-[var(--border)] px-3 py-2 text-sm transition-colors placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed ${autoResize ? 'resize-none overflow-hidden' : ''} ${hasError ? 'border-[var(--rose-7)] focus:ring-[var(--rose-7)]' : 'focus:ring-[var(--violet-6)]'} ${className}`}
          aria-invalid={hasError || undefined}
          aria-describedby={
            error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined
          }
          {...rest}
        />
        {error && (
          <p id={`${inputId}-error`} className="text-xs text-[var(--rose-8)]">
            {error}
          </p>
        )}
        {!error && helperText && (
          <p id={`${inputId}-helper`} className="text-xs text-[var(--text-tertiary)]">
            {helperText}
          </p>
        )}
      </div>
    );
  }),
);

Textarea.displayName = 'Textarea';

export { Textarea };
export type { TextareaProps };
