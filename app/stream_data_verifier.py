class StreamDataVerifier:
    __slots__ = (
        "last_data",
        "total_received",
        "valid_count",
        "lost_count",
        "alarm_count",
    )

    last_data: int | None
    total_received: int
    valid_count: int
    lost_count: int
    alarm_count: int

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_data = None
        self.total_received = 0
        self.valid_count = 0
        self.lost_count = 0
        self.alarm_count = 0

    def check_missing(self, data: int) -> tuple[bool, list[int], int | None]:
        """
        Verifikasi kesinambungan data stream (1-100 secara loop).
        Returns:
            is_valid (bool): True jika data sesuai urutan yang diharapkan.
            missing (list[int]): Daftar angka yang hilang/terlewat.
            expected (int | None): Angka yang diharapkan tiba.
        """
        self.total_received += 1
        missing: list[int] = []
        expected: int | None = None

        if self.last_data is None:
            is_valid = True
            expected = data
        else:
            expected = 1 if self.last_data == 100 else self.last_data + 1
            if data == expected:
                is_valid = True
            else:
                is_valid = False
                # Periksa apakah data duplikat atau di luar jangkauan 1-100
                if data == self.last_data or data < 1 or data > 100:
                    missing = []
                else:
                    # Hitung daftar data yang hilang dari expected sampai data (looping 1-100)
                    curr = expected
                    while curr != data:
                        missing.append(curr)
                        curr = 1 if curr == 100 else curr + 1
                        if len(missing) >= 100:
                            break

                self.lost_count += len(missing)
                self.alarm_count += 1

        if is_valid:
            self.valid_count += 1

        self.last_data = data
        return is_valid, missing, expected

    def verify(self, data: int) -> bool:
        is_valid, _, _ = self.check_missing(data)
        return is_valid
