import { useEffect, useRef } from 'react';

/**
 * Hook that provides accessible modal behaviour:
 * - Escape key closes the modal
 * - The modal container receives focus on open
 * - Returns props (role="dialog", aria-modal) to spread onto the container
 *
 * Usage:
 *   const { modalRef, modalProps } = useModalA11y(isOpen, onClose);
 *   <div ref={modalRef} {...modalProps} tabIndex={-1}> ... </div>
 */
export function useModalA11y(isOpen: boolean, onClose: () => void) {
  const modalRef = useRef<HTMLDivElement>(null);

  // Stabilise onClose so callers don't need to memoise it themselves
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    // Move focus into the modal so screen-readers announce it
    modalRef.current?.focus();

    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const modalProps = {
    role: 'dialog' as const,
    'aria-modal': true as const,
    tabIndex: -1 as const,
  };

  return { modalRef, modalProps };
}
