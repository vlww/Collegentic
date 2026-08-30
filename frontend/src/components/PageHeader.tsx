interface PageHeaderProps {
  title: string;
}

export function PageHeader({ title }: PageHeaderProps) {
  return (
    <h1
      className="mb-6 text-center text-6xl uppercase tracking-wide text-foreground"
      style={{ fontFamily: "'Maintanker', sans-serif" }}
    >
      {title}
    </h1>
  );
}
