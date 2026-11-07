import React, { HTMLProps } from "react";

export interface Props extends HTMLProps<SVGSVGElement> {
  size?: number;
}

export default function RivetLogo({ size = 20, ...props }: Props) {
  return (
    <svg
      role="img"
      aria-label="Rivet AI"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path
        d="M12 2.5 20.5 7.25v9.5L12 21.5 3.5 16.75v-9.5L12 2.5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.75" fill="currentColor" />
    </svg>
  );
}
