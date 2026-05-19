# SESIP Code Review Checklist

Detailed checklist items organized by SESIP control area. Use with `sesip-code-review` SKILL.md.

## Memory Safety

### MS-001: Buffer Overflow - String Copy
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `strcpy\|strcat\|sprintf\|gets` without bounds  
**Remediation:** Use `strncpy`, `snprintf`, `strlcpy`, or explicit size checks

```c
// Vulnerable
strcpy(buf, user_input);

// Fixed
strncpy(buf, user_input, sizeof(buf) - 1);
buf[sizeof(buf) - 1] = '\0';
```

### MS-002: Buffer Overflow - Memory Copy
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `memcpy\|memmove` without source/dest size validation  
**Remediation:** Verify sizes before copy operations

### MS-003: Use-After-Free
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `free\(` followed by dereference, or double-free  
**Remediation:** Set pointer to NULL after free, use-after-free detectors

### MS-004: Dangling Pointer
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** Pointer returned/exposed after underlying buffer freed  
**Remediation:** Clear pointer on free, use smart pointers in C++

### MS-005: Uninitialized Memory
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `malloc\|calloc` without initialization, struct gaps  
**Remediation:** Use `calloc` or explicit memset, initialize all struct fields

### MS-006: Integer Overflow (Size Calculation)
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** Size computation that can overflow (e.g., `n * size`)  
**Remediation:** Check for overflow before allocation, use checked_mul

### MS-007: Heap Overflow
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** Write past heap allocation boundary  
**Remediation:** Bounds check all heap writes

### MS-008: Stack Overflow
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** Large stack allocation, unbounded recursion  
**Remediation:** Limit recursion depth, use heap for large buffers

## Cryptographic Operations

### CR-001: Hardcoded Cryptographic Keys
**SESIP Control:** Cryptographic Operations  
**Severity:** HIGH  
**Pattern:** `"AES\|DES\|key\|secret\|token"` as string literal  
**Remediation:** Use secure key storage (TPM, HSM, keyvault) or secure memory

```c
// Vulnerable
static const char aes_key[] = "mysecretkey123";

// Fixed - load from secure storage at runtime
key = load_key_from_tpm();
```

### CR-002: Weak Cryptographic Algorithms
**SESIP Control:** Cryptographic Operations  
**Severity:** HIGH  
**Pattern:** `DES\|MD5\|SHA1\|RC4\|ECB` in crypto context  
**Remediation:** Use AES-256, SHA-256+, ChaCha20, RSA-2048+

### CR-003: Improper IV/Nonce
**SESIP Control:** Cryptographic Operations  
**Severity:** HIGH  
**Pattern:** Static/zero IV, predictable nonce  
**Remediation:** Use random IV/nonce, never reuse for same key

### CR-004: Missing Cryptographic Seed
**SESIP Control:** Cryptographic Operations  
**Severity:** HIGH  
**Pattern:** `srand\|initstate` without secure seed source  
**Remediation:** Use `/dev/urandom`, `getrandom()`, or hardware RNG

### CR-005: Predictable Random Numbers
**SESIP Control:** Cryptographic Operations  
**Severity:** HIGH  
**Pattern:** `rand\|random` for security-sensitive values  
**Remediation:** Use `arc4random`, `RAND_bytes`, `getrandom()`

### CR-006: Key Derivation Without KDF
**SESIP Control:** Cryptographic Operations  
**Severity:** MEDIUM  
**Pattern:** Password used directly as key  
**Remediation:** Use PBKDF2, Argon2, scrypt for key derivation

### CR-007: Inadequate Entropy
**SESIP Control:** Cryptographic Operations  
**Severity:** MEDIUM  
**Pattern:** Insufficient random bytes for key generation  
**Remediation:** 256-bit minimum for symmetric keys, 2048-bit for RSA

## Input Validation

### IV-001: Unvalidated User Input
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** Direct use of `scanf\|gets\|fgets` without format validation  
**Remediation:** Validate type, range, length before processing

### IV-002: Format String Vulnerability
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** `printf\|sprintf\|fprintf(buf, ...)` where buf is user-controlled  
**Remediation:** Use format string literals: `printf("%s", buf)`

### IV-003: SQL/Command Injection
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** String concatenation for SQL/shell commands  
**Remediation:** Use parameterized queries, shell escape functions

### IV-004: Integer Overflow in Input
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** Size/offset from user used in allocation/array access  
**Remediation:** Validate and bounds-check before use

### IV-005: Path Traversal
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** `../` or absolute paths from user input in file operations  
**Remediation:** Canonicalize paths, validate against allowlist

### IV-006: Type Confusion
**SESIP Control:** Input Validation  
**Severity:** MEDIUM  
**Pattern:** Casting between types without validation  
**Remediation:** Validate type before cast, use union for safe conversion

### IV-007: Missing Bounds Check
**SESIP Control:** Input Validation  
**Severity:** HIGH  
**Pattern:** Array/buffer access without index validation  
**Remediation:** Check bounds before every access

## Session Management

### SM-001: Missing Session Timeout
**SESIP Control:** Session Management  
**Severity:** MEDIUM  
**Pattern:** No timeout on authenticated sessions  
**Remediation:** Implement session timeout (typically 15-30 min inactivity)

### SM-002: Predictable Session IDs
**SESIP Control:** Session Management  
**Severity:** HIGH  
**Pattern:** Sequential or time-based session IDs  
**Remediation:** Use cryptographically random session IDs

### SM-003: Session Fixation
**SESIP Control:** Session Management  
**Severity:** HIGH  
**Pattern:** Not regenerating session ID after authentication  
**Remediation:** Regenerate session ID on privilege change

### SM-004: Insecure Session Storage
**SESIP Control:** Session Management  
**Severity:** MEDIUM  
**Pattern:** Session data in URL, unencrypted local storage  
**Remediation:** Use server-side storage, secure cookies with HttpOnly

## Access Control

### AC-001: Missing Permission Check
**SESIP Control:** Access Control  
**Severity:** HIGH  
**Pattern:** Sensitive operation without access validation  
**Remediation:** Check permissions before every sensitive operation

### AC-002: Insecure Default Credentials
**SESIP Control:** Access Control  
**Severity:** HIGH  
**Pattern:** Default password, hardcoded credentials  
**Remediation:** Force password change on first boot, no defaults

### AC-003: Privilege Escalation
**SESIP Control:** Access Control  
**Severity:** HIGH  
**Pattern:** Running with excessive privileges  
**Remediation:** Use minimum required privilege, drop capabilities early

### AC-004: Insecure File Permissions
**SESIP Control:** Access Control  
**Severity:** MEDIUM  
**Pattern:** `chmod 777`, world-readable sensitive files  
**Remediation:** Use 600/400 for sensitive files, respect umask

### AC-005: Time-of-Check to Time-of-Use (TOCTOU)
**SESIP Control:** Access Control  
**Severity:** MEDIUM  
**Pattern:** Check and use of resource not atomic  
**Remediation:** Use atomic operations, lock files

## Error Handling

### EH-001: Information Leakage in Errors
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** Stack trace, path, version in error messages  
**Remediation:** Log details internally, show generic message externally

### EH-002: Insecure Logging
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** Logging sensitive data (passwords, keys, PII)  
**Remediation:** Sanitize logs, never log secrets

### EH-003: Missing Error Handling
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** Ignoring return values of security functions  
**Remediation:** Check all return values, fail securely

### EH-004: Debug Features in Production
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** `#ifdef DEBUG`, verbose error output  
**Remediation:** Disable debug in production, compile out asserts

### EH-005: Sensitive Data in Core Dumps
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** Core dump without sanitization  
**Remediation:** Sanitize memory before dump, encrypt dumps

## Secure Coding Patterns

### SC-001: TODO Comments in Security Code
**SESIP Control:** Secure Coding  
**Severity:** LOW  
**Pattern:** `TODO\|FIXME\|XXX` in security-sensitive code  
**Remediation:** Complete or track security TODOs separately

### SC-002: Magic Numbers
**SESIP Control:** Secure Coding  
**Severity:** LOW  
**Pattern:** Unnamed numeric constants  
**Remediation:** Use named constants with units in comments

### SC-003: Inconsistent Error Handling
**SESIP Control:** Secure Coding  
**Severity:** MEDIUM  
**Pattern:** Different error handling styles in same module  
**Remediation:** Standardize error handling patterns

### SC-004: Dead Code
**SESIP Control:** Secure Coding  
**Severity:** LOW  
**Pattern:** Unused functions, unreachable code  
**Remediation:** Remove dead code, enable compiler warnings

### SC-005: Complex Security Logic
**SESIP Control:** Secure Coding  
**Severity:** MEDIUM  
**Pattern:** Security logic spanning multiple files without clear interface  
**Remediation:** Centralize security decisions, document assumptions

### SC-006: Missing Asserts in Security Paths
**SESIP Control:** Secure Coding  
**Severity:** LOW  
**Pattern:** No invariant verification in security-critical sections  
**Remediation:** Add asserts to verify pre/post conditions

## Rust-Specific Checks

### RS-001: Unsafe Rust Blocks
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `unsafe {` blocks without safety documentation  
**Remediation:** Document safety invariants, minimize unsafe surface

### RS-002: unwrap() in Production Code
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** `.unwrap()` on Result/Option  
**Remediation:** Handle errors explicitly, use `?` operator

### RS-003: Missing Error Propagation
**SESIP Control:** Error Handling  
**Severity:** MEDIUM  
**Pattern:** Errors silently ignored  
**Remediation:** Propagate errors with `?`, log if truly ignorable

### RS-004: Insecure `unsafe` Functions Exposed
**SESIP Control:** Memory Safety  
**Severity:** HIGH  
**Pattern:** `unsafe fn` without documentation  
**Remediation:** Document safety requirements, validate inputs

## Grep Patterns for Detection

```bash
# Memory Safety
grep -rn 'strcpy\|strcat\|sprintf\|gets' --include="*.c"
grep -rn 'memcpy\|memmove' --include="*.c"
grep -rn 'free.*free\|double.free' --include="*.c"

# Cryptography
grep -rn 'DES\|MD5\|SHA1\|RC4\|ECB' --include="*.c"
grep -rn 'key.*=.*"' --include="*.c"

# Input Validation
grep -rn 'printf.*%s.*buf\|fprintf.*buf' --include="*.c"
grep -rn 'sql.*concatenat\|system.*(' --include="*.c"

# Session Management
grep -rn 'session.*timeout\|SessionTimeout' --include="*.c"

# Access Control
grep -rn 'chmod.*777\|0777' --include="*.c"

# Rust
grep -rn 'unsafe.*{' --include="*.rs"
grep -rn '\.unwrap()' --include="*.rs"
```