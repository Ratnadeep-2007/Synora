# Synora UI setup

Synora uses Next.js 14 App Router, React 18, TypeScript, and Tailwind CSS 3.
Run component commands from `frontend/`, where `components.json` lives.
The configured theme is the existing neutral Vercel-style palette with Geist typography.

## Add components

```powershell
npx shadcn@latest add button
```

For a v0 block, copy its actual Add to Codebase command or registry URL:

```powershell
npx shadcn@latest add "<registry URL copied from v0>"
```

Review proposed file changes before allowing existing application files to be overwritten.
UI primitives resolve to `src/components/ui`; registry blocks can include other paths.
There is no required `components-v0` directory. Initialization is already configured;
running init again can replace project styling.

## Theme convention

`src/app/globals.css` stores complete OKLCH colors. Tailwind maps them with
`var(--token)`, not `hsl(var(--token))`. Keep this convention for imported components;
do not paste bare HSL channels over these variables. Existing Synora aliases and
shadcn semantic tokens share the palette. Both light and `.dark` token sets exist.
The application remains light by default; a complete dark-mode rollout still needs
review of existing hard-coded white surfaces and canvas styling.

`src/lib/utils.ts` exports `cn`. The Tailwind 3-compatible `tailwind-merge` major is 2.
`class-variance-authority` and `tailwindcss-animate` are installed; component-specific
Radix dependencies are installed when the corresponding components are added.

## Check

```powershell
npx tsc --noEmit
```
