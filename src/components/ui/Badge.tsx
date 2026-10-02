import type { HTMLAttributes, ReactNode } from 'react';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'success' | 'danger' | 'blue' | 'yellow' | 'gray';
  size?: 'sm' | 'md';
  dot?: boolean;
  children: ReactNode;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'gray',
  size = 'md',
  dot = false,
  children,
  className = '',
  ...props
}) => {
  const baseStyles = 'inline-flex items-center font-medium rounded-full';

  const sizeStyles = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-xs',
  };

  const variantStyles = {
    success: 'bg-green-100 text-green-800',
    danger: 'bg-red-100 text-red-800',
    blue: 'bg-blue-100 text-blue-800',
    yellow: 'bg-yellow-100 text-yellow-800',
    gray: 'bg-gray-100 text-gray-700',
  };

  const dotColors = {
    success: 'bg-green-600',
    danger: 'bg-red-600',
    blue: 'bg-blue-600',
    yellow: 'bg-yellow-600',
    gray: 'bg-gray-500',
  };

  return (
    <span
      className={`${baseStyles} ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {dot && (
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 shrink-0 ${dotColors[variant]}`}
        />
      )}
      {children}
    </span>
  );
};

export default Badge;
