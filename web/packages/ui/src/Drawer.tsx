import React, { useEffect } from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { X } from 'lucide-react';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  children: React.ReactNode;
  position?: 'right' | 'left';
  width?: 'md' | 'lg' | 'xl';
  className?: string;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  icon,
  children,
  position = 'right',
  width = 'lg',
  className,
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const widthClasses: Record<string, string> = {
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
  };

  const positionClasses = {
    right: 'inset-y-0 right-0 animate-in slide-in-from-right duration-300 border-l',
    left: 'inset-y-0 left-0 animate-in slide-in-from-left duration-300 border-r',
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity animate-in fade-in duration-300"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer Panel */}
      <div
        className={twMerge(
          clsx(
            'fixed flex flex-col w-full bg-[#0E121A] border-[#D4AF37]/35 shadow-[0_0_50px_rgba(0,0,0,0.8)] z-10',
            positionClasses[position],
            widthClasses[width],
            className
          )
        )}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#232B38] bg-white/[0.02] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {icon && <span className="text-[#D4AF37] shrink-0">{icon}</span>}
            <div className="min-w-0">
              {title && (
                <h2 className="font-serif text-sm md:text-base font-bold tracking-wider text-[#F3E5AB] uppercase truncate">
                  {title}
                </h2>
              )}
              {subtitle && (
                <p className="text-xs text-[#8B949E] tracking-tight mt-0.5 truncate">
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[#8B949E] hover:text-[#E6EDF3] hover:bg-[#141A24] border border-transparent hover:border-[#232B38] transition-colors"
            aria-label="Close drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
};
