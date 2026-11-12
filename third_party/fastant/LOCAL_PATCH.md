# Patch local (dv1000 / i686)

Upstream fastant 0.1.10 (crates.io) importe `core::arch::x86_64::__cpuid` sans
cfg, ce qui ne compile pas sur cible 32 bits x86.

Patch unique (src/tsc_now.rs) :

```rust
#[cfg(target_arch = "x86_64")]
use core::arch::x86_64::__cpuid;
#[cfg(target_arch = "x86")]
use core::arch::x86::__cpuid;
```

`_rdtsc()` etait deja correctement gate. Licence MIT d'origine conservee
(voir LICENSE). Aucune autre modification.
