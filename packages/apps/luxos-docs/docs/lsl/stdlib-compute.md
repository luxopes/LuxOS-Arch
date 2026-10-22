# LSL numeric computing: FloatArray kernels, tensor and CUDA

Fast numeric work in Lux Simple Lang: native FloatArray kernels (built-in), the `tensor`
module (CPU tensors) and the optional `cuda` backend. Threads and atomics are in
[builtins.md](builtins.md#threads-and-atomics).

## Choosing a data structure for numbers

For many homogeneous numbers use `IntArray` / `FloatArray` instead of `List`: values are
stored unboxed and contiguous (the manual's sieve of 1,000,000 numbers drops from 2.5 s to
0.03 s). Collect data into a FloatArray and compute with one kernel instead of a loop.

## Native FloatArray kernels (built-in functions)

| Function | Description |
|---|---|
| `float_zeros(n)` | FloatArray of `n` zeros |
| `float_fill(arr, value)` | fill the whole array with a value |
| `float_sum(arr)` | sum of all elements |
| `float_dot(a, b)` | dot product of two FloatArrays |
| `float_axpy(alpha, x, y)` | `y = alpha * x + y` in place (BLAS AXPY); `alpha` must be Float, `x` and `y` the same length; returns `None` |
| `float_matmul(a, b, m, k, n)` | multiply `(m×k) × (k×n)` matrices, return a new `(m×n)` FloatArray |

Kernels use two SSE2 lanes with a scalar tail. `float_sum` and `float_dot` accumulate even and
odd elements separately, so the last bits may differ from a sequential sum on long arrays;
`float_axpy`, `float_fill` and `float_matmul` follow the scalar order exactly.

```lsl
x = float_zeros(2)
y = float_zeros(2)
x[0] = 1.0
x[1] = 2.0
y[0] = 10.0
y[1] = 20.0
call float_axpy(0.5, x, y)
print y          # FloatArray([10.5, 21.0])
```

## tensor — CPU/CUDA tensors

`load tensor`. Errors: `TensorShapeError`, `TensorIndexError`, `TensorLayoutError`.

| Function | Description |
|---|---|
| `tensor.from_values(values, shape)` | Tensor from a flat list of values |
| `tensor.zeros(shape)` | Tensor of zeros |
| `tensor.sum_data(data)` | sum of a FloatArray (CUDA or CPU fallback) |
| `tensor.dot_data(a, b)` | dot product of two FloatArrays |
| `tensor.axpy_data(alpha, x, y)` | AXPY on FloatArrays |
| `tensor.matmul_data(a, b, m, k, n)` | matrix multiplication on FloatArrays |

Tensor class (`Tensor(data, shape, strides, offset, dtype)`, usually via `from_values`):

| Member | Description |
|---|---|
| `t.rank()`, `t.size()` | number of dimensions / elements |
| `t.get([i, j, ...])`, `t.set([i, j, ...], value)` | element access |
| `t.reshape(shape)` | new shape with the same number of elements |
| `t.view(shape, strides, offset)` | zero-copy view sharing data |
| `t.sum()`, `t.dot(other_data)` (rank 1), `t.axpy(alpha, x_data)` | kernels |
| `t.matmul(other_data, other_shape)` | matrix product, new Tensor |
| `t.shape`, `t.data` (FloatArray), `t.dtype` (e.g. `"Float64"`) | fields |
| `t.contiguous_data()` | FloatArray in the logical order of the view |
| `t.to_device(session)` | upload to a DeviceTensor |

```lsl
load tensor
t = tensor.from_values([1, 2, 3, 4, 5, 6], [2, 3])
print t.shape, t.get([1, 2])        # [2, 3] 6.0
a = tensor.from_values([1, 2, 3, 4], [2, 2])
b = tensor.from_values([5, 6, 7, 8], [2, 2])
c = a.matmul(b.data, [2, 2])
```

DeviceTensor provides `rank`, `size`, `to_host`, `reshape`, `free`, `sum`, `dot`, `matmul`,
`transpose`, `add`, `subtract`, `multiply`, `divide`, `scale`, `relu`, `fill`, `axpy`.

## cuda — optional NVIDIA backend

`load cuda`. CUDA runs in a separate worker process (`lsl-cuda-worker`, shipped in the LuxOS
`lsl` package). Without NVIDIA hardware or the worker, the same APIs fall back to the CPU
kernels. Tensor `sum`, `dot`, `axpy`, `matmul` use the GPU automatically only when
`cuda.probe()` verified a real kernel and the work exceeds `LSL_CUDA_MIN_ELEMENTS`.

| Function | Description |
|---|---|
| `cuda.configure(worker, policy, min_elements)` | set worker and policy (`auto`, `required`, `off`) |
| `cuda.probe()` | run a verification kernel, return device metadata or `None` |
| `cuda.available()` | `True` only after a successful device kernel |
| `cuda.devices()` / `cuda.device_count()` | device metadata (`[]` in `auto` mode when unavailable) / count |
| `cuda.backend()` | `"cuda"` or `"cpu"` |
| `cuda.sum_data`, `dot_data`, `axpy_data`, `matmul_data` | GPU operations with CPU fallback |
| `cuda.device()` / `cuda.set_device(index)` | device index for next operations and sessions |
| `cuda.session()` | persistent Session with `upload`, `zeros`, `info`, `synchronize`, `close` |

Buffers have `count`, `download()`, `sum()`, `dot(other)`, `add`, `subtract`, `multiply`,
`divide`, `scale(alpha)`, `relu()`, `fill(value)` (in place), `axpy(alpha, other)` (in place),
`matmul(other, m, k, n)`, `transpose(m, n)` and `free()`.

Environment: `LSL_CUDA_WORKER` (path to the worker), `LSL_CUDA=auto|required|off`,
`LSL_CUDA_DEVICE` (index), `LSL_CUDA_MIN_ELEMENTS` (default 400,000,000 work units).

```lsl
load cuda as gpu
print gpu.probe(), gpu.devices(), gpu.backend()
```

## Performance notes

- The compiler folds constant Int expressions, removes dead branches, uses immediate scalar
  arithmetic and specializes direct non-escaping functions by argument types. Float expressions
  are not folded at compile time (exact NaN/Infinity/signed zero behaviour).
- Garbage collection runs automatically according to allocation volume (since 0.8.4); manual
  `gc()` is optional.
- Use `lsl compile` for repeated runs: compilation happens once and start-up is fast.
