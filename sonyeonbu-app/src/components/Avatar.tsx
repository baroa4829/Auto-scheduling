export default function Avatar({ url, name, size = 48 }: { url?: string; name: string; size?: number }) {
  return url ? (
    <img className="avatar" src={url} alt={name} style={{ width: size, height: size }} />
  ) : (
    <span className="avatar placeholder" style={{ width: size, height: size, fontSize: size * 0.4 }}>
      {name.slice(0, 1) || '?'}
    </span>
  );
}
