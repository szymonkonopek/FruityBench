/* host_file.hpp -- SDK::Interface::IFile over stdio, for the desktop test.
 *
 * The recorder writes through the SDK's own FIT encoder, and that encoder only
 * needs an IFile. Implementing one over stdio lets tools/fit_host_test.cpp run
 * the real fb_fit.cpp + fb_gen.c on a laptop and produce a real .fit file, so
 * the output can be validated (tools/fit_check.py) without flashing a watch.
 *
 * The awkward parts of the contract come from FitWriter::finish(), which
 * back-patches the header and appends the file CRC: it closes and reopens the
 * same handle several times -- read-only, then write WITHOUT truncating -- and
 * relies on size(), getPosition(), seek() and truncate() being exact. Hence:
 *
 *   open(false)        -> "rb"    read, position 0
 *   open(true, true)   -> "w+b"   create/truncate, position 0
 *   open(true, false)  -> "r+b"   open-or-create, NO truncation, position 0
 *
 * "ab" would be wrong for the last case: append ignores seek(), and the header
 * patch writes at offset 0.
 */
#ifndef FB_HOST_FILE_HPP
#define FB_HOST_FILE_HPP

#include <cstdio>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

#include "SDK/Interfaces/IFileSystem.hpp"

class HostFile final : public SDK::Interface::IFile {
public:
    explicit HostFile(const char *path) { setPath(path); }
    ~HostFile() override { closeQuiet(); }

    HostFile(const HostFile &) = delete;
    HostFile &operator=(const HostFile &) = delete;

    /* ---- IFsObject ---------------------------------------------------- */

    void setPath(const char *path) override { mPath = path ? path : ""; }
    const char *getPath() const override { return mPath.c_str(); }

    bool exist() const override
    {
        struct stat st;

        return ::stat(mPath.c_str(), &st) == 0;
    }

    bool rename(const char *newPath) override
    {
        if (!newPath || std::rename(mPath.c_str(), newPath) != 0) {
            return false;
        }
        mPath = newPath;
        return true;
    }

    bool remove() override { return std::remove(mPath.c_str()) == 0; }

    /* ---- IFile -------------------------------------------------------- */

    /* Must be right while the handle is open: finish() reads the header and
     * then compares its data size against this. */
    size_t size() const override
    {
        struct stat st;

        if (mFp) {
            std::fflush(mFp);
        }
        return ::stat(mPath.c_str(), &st) == 0 ? (size_t)st.st_size : 0u;
    }

    bool open(bool wMode = false, bool override_ = false) override
    {
        closeQuiet();
        const char *mode = !wMode ? "rb" : (override_ ? "w+b" : "r+b");

        mFp = std::fopen(mPath.c_str(), mode);
        if (!mFp && wMode && !override_) {
            mFp = std::fopen(mPath.c_str(), "w+b");   /* r+b fails if absent */
        }
        return mFp != nullptr;
    }

    bool isOpen() const override { return mFp != nullptr; }

    bool close() override
    {
        if (!mFp) {
            return false;
        }
        const bool ok = std::fclose(mFp) == 0;

        mFp = nullptr;
        return ok;
    }

    /* A short read at EOF is success with br < btr: the encoder's readExact
     * loop stops on false or on zero bytes. */
    bool read(char *buff, size_t btr, size_t &br) override
    {
        br = 0u;
        if (!mFp) {
            return false;
        }
        br = std::fread(buff, 1, btr, mFp);
        return std::ferror(mFp) == 0;
    }

    bool write(const char *buff, size_t btw, size_t &bw) override
    {
        bw = 0u;
        if (!mFp) {
            return false;
        }
        bw = std::fwrite(buff, 1, btw, mFp);
        return bw == btw;
    }

    bool seek(size_t offset) override
    {
        return mFp && std::fseek(mFp, (long)offset, SEEK_SET) == 0;
    }

    bool truncate(size_t offset) override
    {
        if (!mFp) {
            return false;
        }
        std::fflush(mFp);
        return ::ftruncate(::fileno(mFp), (off_t)offset) == 0;
    }

    bool flush() override { return mFp && std::fflush(mFp) == 0; }

    /* finish() takes this as the data-end offset, so it must be exact. */
    size_t getPosition() const override
    {
        if (!mFp) {
            return 0u;
        }
        const long p = std::ftell(mFp);

        return p < 0 ? 0u : (size_t)p;
    }

private:
    void closeQuiet()
    {
        if (mFp) {
            std::fclose(mFp);
            mFp = nullptr;
        }
    }

    std::string mPath;
    FILE       *mFp = nullptr;
};

#endif /* FB_HOST_FILE_HPP */
