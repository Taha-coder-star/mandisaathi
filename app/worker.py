"""Worker role: claims jobs from the Postgres queue and runs conversation turns (C2/C3)."""
import signal
import time


def main():
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    print("worker ready", flush=True)
    try:
        while not stop:
            time.sleep(1)  # shortcut: idle loop, replaced by the SKIP LOCKED job claim when the queue lands (W1)
    except KeyboardInterrupt:
        pass
    print("worker stopped", flush=True)


if __name__ == "__main__":
    main()
