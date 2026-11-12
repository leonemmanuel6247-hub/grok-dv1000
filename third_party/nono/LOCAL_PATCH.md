# Patch local (dv1000 / i686)

Upstream nono 0.53.0 definissait `SYS_OPENAT`/`SYS_OPENAT2` uniquement pour
x86_64 (257/437) et aarch64 (56/437) — rien pour le 32-bit x86.

Patch unique (src/sandbox/linux.rs) : ajout de

```rust
#[cfg(target_arch = "x86")]
pub const SYS_OPENAT: i32 = 295;   // \_\_NR_openat  (asm/unistd_32.h)
#[cfg(target_arch = "x86")]
pub const SYS_OPENAT2: i32 = 437;  // \_\_NR_openat2 (identique sur 32/64 bits)
```

Aucune autre modification. Licence d'origine du crate conservee (voir Cargo.toml).
Empreintes _raw_ du filtre seccomp inchangees pour x86_64/aarch64.
