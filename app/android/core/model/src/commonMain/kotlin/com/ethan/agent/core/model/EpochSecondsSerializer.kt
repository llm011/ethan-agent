package com.ethan.agent.core.model

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/** Backend stores timestamps as SQLite REAL (float); accept int/long/double JSON numbers. */
object EpochSecondsSerializer : KSerializer<Long> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("EpochSeconds", PrimitiveKind.LONG)

    override fun serialize(encoder: Encoder, value: Long) {
        encoder.encodeLong(value)
    }

    override fun deserialize(decoder: Decoder): Long {
        if (decoder is JsonDecoder) {
            return parseEpoch(decoder.decodeJsonElement())
        }
        return decoder.decodeLong()
    }

    internal fun parseEpoch(element: kotlinx.serialization.json.JsonElement): Long {
        if (element !is JsonPrimitive) return 0L
        if (element.isString) {
            return element.content.toDoubleOrNull()?.toLong() ?: 0L
        }
        return element.doubleOrNull?.toLong()
            ?: element.longOrNull
            ?: 0L
    }
}

object NullableEpochSecondsSerializer : KSerializer<Long?> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("EpochSecondsNullable", PrimitiveKind.LONG)

    override fun serialize(encoder: Encoder, value: Long?) {
        if (value == null) encoder.encodeNull() else encoder.encodeLong(value)
    }

    override fun deserialize(decoder: Decoder): Long? {
        if (decoder is JsonDecoder) {
            val element = decoder.decodeJsonElement()
            if (element is JsonPrimitive && element.isString && element.content == "null") return null
            return EpochSecondsSerializer.parseEpoch(element)
        }
        return decoder.decodeLong()
    }
}

typealias EpochSeconds = @Serializable(with = EpochSecondsSerializer::class) Long

typealias EpochSecondsNullable = @Serializable(with = NullableEpochSecondsSerializer::class) Long?
