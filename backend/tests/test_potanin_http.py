from app.sources.adapters.potanin.http import encode_request_url


def test_transport_url_encodes_non_ascii_file_names_without_changing_structure() -> None:
    assert encode_request_url(
        "https://fondpotanin.ru/upload/Документы/итоги конкурса.pdf?год=2026"
    ) == (
        "https://fondpotanin.ru/upload/%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD%D1%82%D1%8B/"
        "%D0%B8%D1%82%D0%BE%D0%B3%D0%B8%20%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D1%81%D0%B0.pdf?"
        "%D0%B3%D0%BE%D0%B4=2026"
    )
