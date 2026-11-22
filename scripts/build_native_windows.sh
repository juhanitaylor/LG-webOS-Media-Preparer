#!/usr/bin/env bash
# Run from the loggable Windows build driver with a short, disposable build path.
set -euo pipefail
export PATH=/ucrt64/bin:/usr/bin
export LC_ALL=C
cd "$1"
root="$PWD"
source="$root/source"
prefix="$root/prefix"
jobs="$2"
mkdir -p "$prefix" "$root/payload"
export PKG_CONFIG_LIBDIR="$(cygpath -am "$prefix/lib/pkgconfig")"
export CMAKE_BUILD_PARALLEL_LEVEL="$jobs"

compile_cmake() {
    local name="$1"
    shift
    cmake -S "$source/$name" -B "$root/$name" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_PREFIX_PATH="$prefix" \
        -DCMAKE_EXE_LINKER_FLAGS=-static "$@"
    cmake --build "$root/$name"
    cmake --install "$root/$name"
}

compile_cmake zlib -DZLIB_BUILD_SHARED=OFF -DZLIB_BUILD_TESTING=OFF
cp "$prefix/lib/libzs.a" "$prefix/lib/libz.a"
zlib=(-DZLIB_LIBRARY="$prefix/lib/libzs.a" -DZLIB_INCLUDE_DIR="$prefix/include")
compile_cmake libpng -DPNG_SHARED=OFF -DPNG_TESTS=OFF -DPNG_TOOLS=OFF "${zlib[@]}"
compile_cmake leptonica -DSW_BUILD=OFF -DSTRICT_CONF=ON -DENABLE_GIF=OFF \
    -DENABLE_JPEG=OFF -DENABLE_TIFF=OFF -DENABLE_WEBP=OFF -DENABLE_OPENJPEG=OFF "${zlib[@]}"
compile_cmake tesseract -DSW_BUILD=OFF -DGRAPHICS_DISABLED=ON -DBUILD_TRAINING_TOOLS=OFF \
    -DOPENMP_BUILD=OFF -DDISABLE_TIFF=ON -DDISABLE_CURL=ON -DDISABLE_ARCHIVE=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_OpenCL=TRUE -DENABLE_NATIVE=OFF \
    -DLEPT_TIFF_RESULT=1 -DLEPT_TIFF_COMPILE_SUCCESS=TRUE "${zlib[@]}"
install -m 755 "$prefix/bin/tesseract.exe" "$root/payload/tesseract.exe"

cd "$source/x264"
./configure --prefix="$prefix" --host=x86_64-w64-mingw32 --enable-static --disable-cli --disable-opencl
make -j "$jobs"
make install

cd "$source/ffmpeg"
./configure --enable-gpl --enable-libx264 --enable-zlib --disable-autodetect --disable-network \
    --disable-doc --disable-programs --enable-ffmpeg --enable-ffprobe --disable-shared --enable-static \
    --enable-runtime-cpudetect --pkg-config-flags=--static --arch=x86_64 --target-os=mingw64 \
    --extra-cflags="-I$prefix/include -D_WIN32_WINNT=0x0A00" --extra-ldflags="-static -L$prefix/lib" \
    --prefix="$prefix"
make -j "$jobs" ffmpeg.exe ffprobe.exe
install -m 755 ffmpeg.exe ffprobe.exe "$root/payload/"
strip "$root/payload/"*.exe
