interface PagePlaceholderProps {
  title: string
}

// Stands in for every page until its own commit builds the real one (Phase D).
// Existing only to make navigation reviewable before any page has content.
export function PagePlaceholder({ title }: PagePlaceholderProps) {
  return (
    <div>
      <h1>{title}</h1>
      <p>Coming soon.</p>
    </div>
  )
}
